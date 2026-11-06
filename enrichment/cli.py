"""Enrich HubSpot companies with Wikidata.

    python -m enrichment.cli --dry-run      # show what would change, write nothing
    python -m enrichment.cli                # apply changes
    python -m enrichment.cli --limit 5      # only the first 5 companies with a domain

Each run: make sure the custom properties exist, page through companies,
look their domains up in Wikidata, choose a match (see matching.py), and
batch-update only the values that actually changed.
"""

import argparse
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from enrichment.config import load_hubspot_token
from enrichment.domains import normalize_domain
from enrichment.hubspot import HubSpotClient
from enrichment.matching import choose_candidate
from enrichment.properties import COMPANY_PROPERTIES, ensure_properties
from enrichment.wikidata import WikidataClient

# What HubSpot already knows, used as matching evidence.
EVIDENCE_PROPERTIES = ["name", "domain", "founded_year", "country", "numberofemployees"]
ENRICHED_PROPERTIES = [p["name"] for p in COMPANY_PROPERTIES if p["name"] != "normalized_domain"]


@dataclass
class Plan:
    updates: list = field(default_factory=list)  # [{"id", "properties"}] ready for batch update
    changes: dict = field(default_factory=dict)  # company name -> {property: (old, new)}
    matches: dict = field(default_factory=dict)  # company name -> winning ScoredCandidate
    unchanged: list = field(default_factory=list)
    no_item: list = field(default_factory=list)  # no Wikidata item has this website
    rejected: list = field(default_factory=list)  # (company name, MatchResult): only non-organizations
    ambiguous: list = field(default_factory=list)  # (company name, MatchResult)
    no_domain: list = field(default_factory=list)


def enriched_values(candidate):
    """The HubSpot property values a matched candidate provides. Missing data is left out, not blanked."""
    values = {
        "wikidata_id": candidate.qid,
        "wikidata_industry": "; ".join(candidate.industries) or None,
        "wikidata_founded_year": candidate.founded_year,
        "wikidata_employee_count": candidate.employee_count,
    }
    return {key: str(value) for key, value in values.items() if value is not None}


def same_value(current, new):
    """HubSpot returns every value as a string; compare numbers numerically ("2002" == "2002.0")."""
    if current is None or current == "":
        return False
    try:
        return float(current) == float(new)
    except ValueError:
        return current == new


def plan_updates(companies, candidates_by_domain):
    """Decide what to write, without writing anything."""
    plan = Plan()

    for company in companies:
        props = company["properties"]
        name = props.get("name") or f"(company {company['id']})"
        domain = normalize_domain(props.get("domain"))

        if not domain:
            plan.no_domain.append(name)
            continue

        result = choose_candidate(candidates_by_domain.get(domain, []), props)
        if result.status == "not_found":
            if result.excluded:
                plan.rejected.append((name, result))
            else:
                plan.no_item.append(name)
            continue
        if result.status == "ambiguous":
            plan.ambiguous.append((name, result))
            continue

        plan.matches[name] = result.best
        changed = {
            key: value
            for key, value in enriched_values(result.candidate).items()
            if not same_value(props.get(key), value)
        }
        if not changed:
            plan.unchanged.append(name)
            continue

        plan.updates.append({"id": company["id"], "properties": changed})
        plan.changes[name] = {key: (props.get(key), value) for key, value in changed.items()}

    return plan


def describe(scored):
    """One line of audit trail: which item, its score, and why."""
    c = scored.candidate
    return f"{c.qid} ({c.label or 'no label'}) score {scored.score}: {'; '.join(scored.reasons)}"


def print_report(plan, dry_run, errors=()):
    verb = "Would update" if dry_run else "Updated"
    print(f"\n{verb} {len(plan.updates)} companies:")
    for name, changes in sorted(plan.changes.items()):
        best = plan.matches[name]
        print(f"  {name}  [{describe(best)}]")
        for key, (old, new) in changes.items():
            print(f"      {key}: {old or '(empty)'} -> {new}")

    print(f"\nUnchanged: {len(plan.unchanged)}")
    if plan.unchanged:
        print(f"  {', '.join(sorted(plan.unchanged))}")

    print(f"\nNo Wikidata item with this website: {len(plan.no_item)}")
    if plan.no_item:
        print(f"  {', '.join(sorted(plan.no_item))}")

    print(f"\nOnly non-organization matches, rejected: {len(plan.rejected)}")
    for name, result in sorted(plan.rejected, key=lambda r: r[0]):
        print(f"  {name}")
        for reason in result.excluded:
            print(f"      {reason}")

    print(f"\nAmbiguous, needs review: {len(plan.ambiguous)}")
    for name, result in plan.ambiguous:
        print(f"  {name}")
        for scored in result.scored[:3]:
            print(f"      {describe(scored)}")

    if plan.no_domain:
        print(f"\nSkipped, no usable domain: {len(plan.no_domain)}")
        print(f"  {', '.join(sorted(plan.no_domain))}")

    if errors:
        print(f"\nFailed: {len(errors)}")
        for error in errors:
            print(f"  {error.get('message')}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Enrich HubSpot companies with Wikidata.")
    parser.add_argument("--dry-run", action="store_true", help="show changes without writing them")
    parser.add_argument("--limit", type=int, help="only process this many companies with a domain")
    args = parser.parse_args(argv)

    hubspot = HubSpotClient(load_hubspot_token())
    wikidata = WikidataClient()
    timings = {}

    with timed(timings, "HubSpot: properties"):
        missing = ensure_properties(hubspot, dry_run=args.dry_run)
    if missing:
        action = "Would create" if args.dry_run else "Created"
        print(f"{action} properties: {', '.join(missing)}")

    with timed(timings, "HubSpot: read companies"):
        all_companies = list(hubspot.iter_companies(EVIDENCE_PROPERTIES + ENRICHED_PROPERTIES))
    companies = [c for c in all_companies if normalize_domain(c["properties"].get("domain"))]
    if args.limit:
        companies = companies[: args.limit]
    print(f"Checking {len(companies)} companies against Wikidata...")

    domains = [normalize_domain(c["properties"]["domain"]) for c in companies]
    candidates = wikidata.find_candidates(domains)
    timings.update(wikidata.timings)

    with timed(timings, "Matching and planning"):
        plan = plan_updates(companies, candidates)
    plan.no_domain = [
        c["properties"].get("name") or f"(company {c['id']})"
        for c in all_companies
        if not normalize_domain(c["properties"].get("domain"))
    ]

    errors = []
    if plan.updates and not args.dry_run:
        with timed(timings, "HubSpot: batch update"):
            _, errors = hubspot.batch_update_companies(plan.updates)

    print_report(plan, args.dry_run, errors)
    print_timings(timings)
    return 1 if errors else 0


@contextmanager
def timed(timings, phase):
    started = time.perf_counter()
    try:
        yield
    finally:
        timings[phase] = timings.get(phase, 0.0) + time.perf_counter() - started


def print_timings(timings):
    print(f"\nTiming ({sum(timings.values()):.1f}s total):")
    for phase, seconds in timings.items():
        print(f"  {phase:<30} {seconds:6.2f}s")


if __name__ == "__main__":
    sys.exit(main())
