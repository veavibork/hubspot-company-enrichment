"""Enrich HubSpot companies with Wikidata and SEC EDGAR.

    python -m enrichment.cli --dry-run      # show what would change, write nothing
    python -m enrichment.cli                # apply changes
    python -m enrichment.cli --limit 5      # only the first 5 companies with a domain

Each run: make sure the custom properties exist, page through companies,
look their domains up in Wikidata, choose a match (see matching.py), look
matched companies' CIKs up in EDGAR (if SEC_USER_AGENT is set), and
batch-update only the values that actually changed.
"""

import argparse
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from enrichment.config import load_hubspot_token, load_sec_user_agent
from enrichment.domains import normalize_domain
from enrichment.edgar import EdgarClient, normalize_cik
from enrichment.hubspot import HubSpotClient
from enrichment.matching import NAME_PARTIAL, choose_candidate, name_score
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
    edgar: dict = field(default_factory=dict)  # EDGAR status -> company names; empty if EDGAR is off
    edgar_conflicts: list = field(default_factory=list)  # (company name, name on file with the SEC)


def enriched_values(candidate):
    """The HubSpot property values a matched candidate provides. Missing data is left out, not blanked."""
    values = {
        "wikidata_id": candidate.qid,
        "wikidata_industry": "; ".join(candidate.industries) or None,
        "wikidata_founded_year": candidate.founded_year,
        "wikidata_employee_count": candidate.employee_count,
    }
    return {key: str(value) for key, value in values.items() if value is not None}


def match_values(status, score, reasons, today):
    """Match outcome properties, written for every company checked. An empty string clears a stale value."""
    return {
        "wikidata_match_status": status,
        "wikidata_match_score": "" if score is None else str(score),
        "wikidata_match_reasons": reasons,
        "wikidata_last_checked": today,
    }


def same_value(current, new):
    """HubSpot returns every value as a string; compare numbers numerically ("2002" == "2002.0")."""
    if current is None or current == "":
        return new == ""
    try:
        return float(current) == float(new)
    except ValueError:
        return current == new


def match_companies(companies, candidates_by_domain):
    """Choose a Wikidata match for each company with a domain. Returns {company id: MatchResult}."""
    results = {}
    for company in companies:
        domain = normalize_domain(company["properties"].get("domain"))
        if domain:
            results[company["id"]] = choose_candidate(
                candidates_by_domain.get(domain, []), company["properties"]
            )
    return results


def matched_ciks(results):
    """CIKs of Wikidata-matched companies, for the EDGAR lookup."""
    return {
        normalize_cik(r.candidate.cik)
        for r in results.values()
        if r.status == "matched" and r.candidate.cik
    }


def edgar_values(result, records, hubspot_name, today):
    """EDGAR properties for one company. records maps CIK -> EdgarCompany (or None if the SEC has no such filer).

    The CIK comes from Wikidata, which can attach it to the wrong item, so the
    SEC's name for the company must agree with HubSpot's before anything is written.
    Returns (status, values).
    """
    cik = normalize_cik(result.candidate.cik) if result.status == "matched" and result.candidate.cik else None
    if not cik:
        return "no_cik", {"edgar_match_status": "no_cik", "edgar_last_checked": today}

    record = records.get(cik)
    if record is None:
        return "not_found", {"edgar_cik": cik, "edgar_match_status": "not_found", "edgar_last_checked": today}

    if name_score(hubspot_name, [record.name]) < NAME_PARTIAL:
        return "name_conflict", {
            "edgar_cik": cik,
            "edgar_name": record.name,
            "edgar_match_status": "name_conflict",
            "edgar_last_checked": today,
        }

    values = {
        "edgar_cik": cik,
        "edgar_name": record.name,
        "edgar_ticker": ", ".join(record.tickers) or None,
        "edgar_exchange": ", ".join(record.exchanges) or None,
        "edgar_sic_description": record.sic_description,
        "edgar_filer_category": record.filer_category,
        "edgar_state_of_incorporation": record.state_of_incorporation,
        "edgar_business_location": record.business_location,
        "edgar_annual_revenue": record.annual_revenue,
        "edgar_revenue_fiscal_year": record.revenue_fiscal_year,
        "edgar_match_status": "matched",
        "edgar_last_checked": today,
    }
    return "matched", {key: str(value) for key, value in values.items() if value is not None}


def plan_updates(companies, results, today=None, edgar_records=None):
    """Decide what to write, without writing anything.

    Every company with a domain gets its match outcome recorded. Only matched
    companies get Wikidata values; earlier values on a now-unmatched company
    are left in place, and its status shows the current outcome.

    edgar_records is None when EDGAR isn't configured; then no EDGAR
    properties are touched at all.
    """
    today = today or datetime.now(timezone.utc).date().isoformat()
    plan = Plan()

    for company in companies:
        props = company["properties"]
        name = props.get("name") or f"(company {company['id']})"

        result = results.get(company["id"])
        if result is None:
            plan.no_domain.append(name)
            continue

        if result.status == "matched":
            plan.matches[name] = result.best
            desired = enriched_values(result.candidate)
            desired.update(match_values("matched", result.best.score, describe(result.best), today))
        elif result.status == "ambiguous":
            plan.ambiguous.append((name, result))
            reasons = "\n".join(describe(s) for s in result.scored[:3])
            desired = match_values("ambiguous", result.best.score, reasons, today)
        elif result.excluded:
            plan.rejected.append((name, result))
            desired = match_values("rejected", None, "\n".join(result.excluded), today)
        else:
            plan.no_item.append(name)
            desired = match_values("no_item", None, "No Wikidata item has this website.", today)

        if edgar_records is not None:
            status, values = edgar_values(result, edgar_records, props.get("name"), today)
            plan.edgar.setdefault(status, []).append(name)
            if status == "name_conflict":
                plan.edgar_conflicts.append((name, values["edgar_name"]))
            desired.update(values)

        changed = {
            key: value for key, value in desired.items() if not same_value(props.get(key), value)
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
        best = plan.matches.get(name)
        print(f"  {name}  [{describe(best)}]" if best else f"  {name}")
        for key, (old, new) in changes.items():
            if key == "wikidata_match_reasons":
                continue  # already shown above, or in the sections below
            print(f"      {key}: {old or '(empty)'} -> {new or '(cleared)'}")

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

    if not plan.edgar:
        print("\nEDGAR: skipped (set SEC_USER_AGENT in .env to enable)")
    else:
        print("\nEDGAR (by CIK from Wikidata):")
        for status, label in [
            ("matched", "Matched"),
            ("name_conflict", "Name conflict, needs review"),
            ("not_found", "CIK not found in EDGAR"),
            ("no_cik", "No CIK available"),
        ]:
            names = plan.edgar.get(status, [])
            print(f"  {label}: {len(names)}" + (f"  ({', '.join(sorted(names))})" if names else ""))
        for name, sec_name in plan.edgar_conflicts:
            print(f"      {name}: the SEC has this CIK registered to {sec_name!r}")

    if errors:
        print(f"\nFailed: {len(errors)}")
        for error in errors:
            print(f"  {error.get('message')}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Enrich HubSpot companies with Wikidata and SEC EDGAR.")
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

    with timed(timings, "Matching"):
        results = match_companies(companies, candidates)

    edgar_records = None
    sec_user_agent = load_sec_user_agent()
    if sec_user_agent:
        with timed(timings, "EDGAR: fetch"):
            edgar_records = EdgarClient(sec_user_agent).companies(matched_ciks(results))

    with timed(timings, "Planning"):
        plan = plan_updates(companies, results, edgar_records=edgar_records)
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
