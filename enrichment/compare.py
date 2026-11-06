"""Read-only comparison of HubSpot, Wikidata and EDGAR values already stored in HubSpot."""

import argparse
import sys
from dataclasses import dataclass, field

from enrichment.config import load_hubspot_token
from enrichment.hubspot import HubSpotClient
from enrichment.sec_lookup import state_code

PROPERTIES = [
    "name", "is_public", "state", "industry", "founded_year", "numberofemployees", "annualrevenue",
    "wikidata_founded_year", "wikidata_employee_count", "wikidata_industry",
    "edgar_match_status", "edgar_ticker", "edgar_business_location", "edgar_state_of_incorporation",
    "edgar_annual_revenue", "edgar_revenue_fiscal_year", "edgar_sic_description",
]


@dataclass
class Comparison:
    title: str
    sources: str
    outcomes: dict = field(default_factory=dict)  # outcome label -> [(company name, detail)]

    def add(self, outcome, name, detail=""):
        self.outcomes.setdefault(outcome, []).append((name, detail))

    @property
    def compared(self):
        return sum(len(v) for k, v in self.outcomes.items() if k != NOT_COMPARABLE)


NOT_COMPARABLE = "not comparable (a value is missing)"

# Numbers within this ratio "agree"; the UI card uses the same value.
AGREEMENT_RATIO = 1.1


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio_bucket(a, b):
    ratio = max(a, b) / min(a, b)
    if ratio <= AGREEMENT_RATIO:
        return "within 10%"
    if ratio <= 1.5:
        return "10-50% apart"
    if ratio <= 3:
        return "1.5-3x apart"
    return "more than 3x apart"


def compare_public(rows):
    c = Comparison("Public or private", "HubSpot `is_public` vs EDGAR ticker")
    for name, p in rows:
        hubspot = (p.get("is_public") or "").lower()
        if hubspot not in ("true", "false") or p.get("edgar_match_status") != "matched":
            c.add(NOT_COMPARABLE, name)
            continue
        hubspot_public = hubspot == "true"
        edgar_public = bool(p.get("edgar_ticker"))
        detail = f"HubSpot {'public' if hubspot_public else 'private'}, EDGAR {'ticker ' + p['edgar_ticker'] if edgar_public else 'no ticker'}"
        c.add("agree" if hubspot_public == edgar_public else "disagree", name, detail)
    return c


def compare_location(rows):
    c = Comparison("Location (US state)", "HubSpot `state` vs EDGAR business address and state of incorporation")
    for name, p in rows:
        hubspot = state_code(p.get("state"))
        location = p.get("edgar_business_location") or ""
        business = state_code(location.rsplit(",", 1)[-1]) if "," in location else None
        incorporation = state_code(p.get("edgar_state_of_incorporation"))
        if not hubspot or not (business or incorporation):
            c.add(NOT_COMPARABLE, name)
            continue
        detail = f"HubSpot {hubspot}; EDGAR business {business or '?'}, incorporated {incorporation or '?'}"
        if hubspot == business:
            c.add("HubSpot matches business address", name, detail)
        elif hubspot == incorporation:
            c.add("HubSpot matches state of incorporation only", name, detail)
        else:
            c.add("HubSpot matches neither", name, detail)
    return c


def compare_founded(rows):
    c = Comparison("Founded year", "HubSpot `founded_year` vs Wikidata")
    for name, p in rows:
        hubspot, wikidata = _number(p.get("founded_year")), _number(p.get("wikidata_founded_year"))
        if not hubspot or not wikidata:
            c.add(NOT_COMPARABLE, name)
            continue
        diff = abs(hubspot - wikidata)
        detail = f"HubSpot {int(hubspot)}, Wikidata {int(wikidata)}"
        c.add("same year" if diff == 0 else "1 year apart" if diff == 1 else "more than 1 year apart", name, detail)
    return c


def compare_numbers(rows, title, sources, hubspot_key, other_key, other_label, money=False):
    c = Comparison(title, sources)
    for name, p in rows:
        hubspot, other = _number(p.get(hubspot_key)), _number(p.get(other_key))
        if not hubspot or not other:
            c.add(NOT_COMPARABLE, name)
            continue
        fmt = (lambda v: f"${v / 1e9:.2f}B" if v >= 1e9 else f"${v / 1e6:.0f}M") if money else (lambda v: f"{int(v):,}")
        c.add(_ratio_bucket(hubspot, other), name, f"HubSpot {fmt(hubspot)}, {other_label} {fmt(other)}")
    return c


def industries(rows):
    # Three classification systems: side by side, no verdict.
    return [
        (name, p.get("industry") or "", p.get("wikidata_industry") or "", p.get("edgar_sic_description") or "")
        for name, p in rows
    ]


def build_comparisons(rows):
    return [
        compare_public(rows),
        compare_location(rows),
        compare_founded(rows),
        compare_numbers(rows, "Employee count", "HubSpot `numberofemployees` vs Wikidata",
                        "numberofemployees", "wikidata_employee_count", "Wikidata"),
        compare_numbers(rows, "Annual revenue", "HubSpot `annualrevenue` vs EDGAR (latest 10-K)",
                        "annualrevenue", "edgar_annual_revenue", "EDGAR", money=True),
    ]


def print_text(comparisons, industry_rows):
    for c in comparisons:
        print(f"\n{c.title}  ({c.sources}); {c.compared} companies compared")
        for outcome, entries in c.outcomes.items():
            print(f"  {outcome}: {len(entries)}")
            if outcome != NOT_COMPARABLE:
                for name, detail in entries:
                    print(f"      {name}: {detail}")
    print("\nIndustry (side by side; three classification systems)")
    for name, hubspot, wikidata, sic in industry_rows:
        print(f"  {name}: HubSpot {hubspot or '-'} | Wikidata {wikidata or '-'} | EDGAR SIC {sic or '-'}")


def print_markdown(comparisons, industry_rows):
    for c in comparisons:
        print(f"\n**{c.title}** ({c.sources}; {c.compared} companies compared)\n")
        print("| Outcome | Companies |")
        print("|---|---|")
        for outcome, entries in c.outcomes.items():
            if outcome == NOT_COMPARABLE:
                continue
            listed = "; ".join(f"{name} ({detail})" for name, detail in entries)
            print(f"| {outcome} | {len(entries)}: {listed} |")
    print("\n**Industry** (three classification systems, side by side)\n")
    print("| Company | HubSpot | Wikidata | EDGAR SIC |")
    print("|---|---|---|---|")
    for name, hubspot, wikidata, sic in industry_rows:
        print(f"| {name} | {hubspot or '-'} | {wikidata or '-'} | {sic or '-'} |")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare HubSpot, Wikidata and EDGAR values. Read-only.")
    parser.add_argument("--markdown", action="store_true", help="print Markdown tables")
    args = parser.parse_args(argv)

    hubspot = HubSpotClient(load_hubspot_token())
    rows = sorted(
        ((c["properties"].get("name") or c["id"], c["properties"]) for c in hubspot.iter_companies(PROPERTIES)),
        key=lambda r: r[0],
    )
    comparisons, industry_rows = build_comparisons(rows), industries(rows)
    (print_markdown if args.markdown else print_text)(comparisons, industry_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
