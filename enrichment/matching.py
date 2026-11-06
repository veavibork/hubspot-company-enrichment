"""Choose which Wikidata candidate, if any, is the same company as a HubSpot record.

Every candidate already shares the company's website. That's necessary but
not sufficient: people, software products and duplicate legal-entity records
list the same website. So:

1. Only organizations are considered.
2. Each organization is scored on independent evidence: name, website rank,
   and agreement with what HubSpot already knows (founded year, country,
   employee count). HubSpot-based signals count only when HubSpot has a value.
3. Sitelinks (how many Wikipedias cover the item) only break exact ties.
4. If the evidence is weak or can't separate the top candidates, the result
   is "ambiguous" and nothing should be written. A wrong match does more harm
   than no match, because it looks trustworthy.
"""

import re
from dataclasses import dataclass, field

from enrichment.countries import to_iso2

MIN_SCORE = 3

NAME_EXACT = 3
NAME_PARTIAL = 2
FOUNDED_AGREES = 2
FOUNDED_DISAGREES = -2
COUNTRY_AGREES = 1
COUNTRY_DISAGREES = -1
EMPLOYEES_FAR_OFF = -1
RANK_PREFERRED = 1
RANK_DEPRECATED = -1

FOUNDED_TOLERANCE_YEARS = 1
EMPLOYEE_RATIO_LIMIT = 10

LEGAL_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "llc",
    "ltd", "limited", "plc", "pty", "gmbh", "ag", "sa", "bv", "nv",
}

# Not legal forms, but stripped the same way: "Salesforce.com, Inc." -> "salesforce".
# Found with `python -m enrichment.check_suffixes`.
NAME_SUFFIXES = LEGAL_SUFFIXES | {"com"}



@dataclass
class ScoredCandidate:
    candidate: object
    score: int
    reasons: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    status: str  # "matched", "ambiguous" or "not_found"
    best: ScoredCandidate | None = None
    scored: list[ScoredCandidate] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)

    @property
    def candidate(self):
        return self.best.candidate if self.best else None


def choose_candidate(candidates, company):
    """Pick the best candidate for a HubSpot company.

    company: the record's HubSpot properties, e.g.
        {"name": "Wayfair", "founded_year": "2002", "country": "United States",
         "numberofemployees": "2000"}
    """
    excluded = [
        f"{c.qid} ({c.label or 'no label'}): not an organization"
        for c in candidates
        if not c.is_organization
    ]
    organizations = [c for c in candidates if c.is_organization]

    if not organizations:
        return MatchResult("not_found", excluded=excluded)

    scored = sorted(
        (score_candidate(c, company) for c in organizations),
        key=lambda s: (s.score, s.candidate.sitelinks),
        reverse=True,
    )
    best = scored[0]

    if best.score < MIN_SCORE:
        return MatchResult("ambiguous", best, scored, excluded)

    if len(scored) > 1:
        runner_up = scored[1]
        if (runner_up.score, runner_up.candidate.sitelinks) == (
            best.score,
            best.candidate.sitelinks,
        ):
            return MatchResult("ambiguous", best, scored, excluded)

    return MatchResult("matched", best, scored, excluded)


def score_candidate(candidate, company):
    score, reasons = 0, []

    def add(points, reason):
        nonlocal score
        score += points
        reasons.append(f"{points:+d} {reason}")

    name_points = name_score(company.get("name"), [candidate.label, *candidate.aliases])
    if name_points == NAME_EXACT:
        add(NAME_EXACT, "name matches")
    elif name_points == NAME_PARTIAL:
        add(NAME_PARTIAL, "name partly matches")

    if candidate.website_rank == "preferred":
        add(RANK_PREFERRED, "website is Wikidata's preferred value")
    elif candidate.website_rank == "deprecated":
        add(RANK_DEPRECATED, "website is marked deprecated in Wikidata")

    hubspot_year = _int(company.get("founded_year"))
    if hubspot_year and candidate.founded_year:
        if abs(hubspot_year - candidate.founded_year) <= FOUNDED_TOLERANCE_YEARS:
            add(FOUNDED_AGREES, f"founded year agrees ({candidate.founded_year})")
        else:
            add(
                FOUNDED_DISAGREES,
                f"founded year disagrees ({candidate.founded_year} vs HubSpot {hubspot_year})",
            )

    # Compared as ISO codes. A HubSpot value we can't resolve gives no signal,
    # rather than counting as a disagreement.
    hubspot_country = to_iso2(company.get("country"))
    if hubspot_country and candidate.country_code:
        if hubspot_country == candidate.country_code:
            add(COUNTRY_AGREES, f"country agrees ({candidate.country})")
        else:
            add(
                COUNTRY_DISAGREES,
                f"country disagrees ({candidate.country} vs HubSpot {company.get('country')})",
            )

    hubspot_employees = _int(company.get("numberofemployees"))
    if hubspot_employees and candidate.employee_count:
        ratio = max(hubspot_employees, candidate.employee_count) / min(
            hubspot_employees, candidate.employee_count
        )
        if ratio > EMPLOYEE_RATIO_LIMIT:
            add(
                EMPLOYEES_FAR_OFF,
                f"employee count far off ({candidate.employee_count} vs HubSpot {hubspot_employees})",
            )

    return ScoredCandidate(candidate, score, reasons)


def name_score(company_name, candidate_names):
    """3 if a candidate name matches after normalizing, 2 if one contains the other's words, else 0."""
    target = normalize_name(company_name)
    if not target:
        return 0

    best = 0
    for name in candidate_names:
        other = normalize_name(name)
        if not other:
            continue
        if other == target:
            return NAME_EXACT
        a, b = set(target.split()), set(other.split())
        if a <= b or b <= a:
            best = NAME_PARTIAL
    return best


def normalize_name(name):
    """Lowercase, drop punctuation and legal suffixes: "Wayfair, Inc." -> "wayfair"."""
    if not name:
        return ""
    words = re.sub(r"[^\w\s]", " ", name.lower()).split()
    while words and words[-1] in NAME_SUFFIXES:
        words.pop()
    return " ".join(words)


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
