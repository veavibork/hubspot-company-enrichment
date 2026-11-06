"""Look up companies in Wikidata by their official website.

Returns every Wikidata item whose official website (P856) matches a domain,
along with the facts needed to score it. Choosing between candidates is the
job of enrichment/matching.py, not this module.
"""

import time
from dataclasses import dataclass, field

import requests

from enrichment.domains import normalize_domain
from enrichment.retries import request_with_retries

SPARQL_URL = "https://query.wikidata.org/sparql"

# Wikimedia asks API clients to identify themselves with a contact point.
USER_AGENT = (
    "hubspot-company-enrichment/0.1 "
    "(https://github.com/veavibork/hubspot-company-enrichment)"
)

DOMAINS_PER_QUERY = 25

# wd:Q43229 is "organization". Anything that is an instance of it, or of
# a subclass of it, counts; people and software packages don't.
#
# Labels fall back from "en" to "mul" (Wikidata's language-neutral label):
# many items, Etsy among them, now store their name only under "mul".
QUERY_TEMPLATE = """
SELECT ?site ?item ?label ?sitelinks ?rank ?isOrg
       (MIN(?inception) AS ?founded)
       (SAMPLE(?countryLabel) AS ?country)
       (SAMPLE(?countryIso) AS ?countryCode)
       (SAMPLE(?cikValue) AS ?cik)
       (GROUP_CONCAT(DISTINCT ?alias; separator="|") AS ?aliases)
       (GROUP_CONCAT(DISTINCT ?industryLabel; separator="|") AS ?industries)
       (GROUP_CONCAT(DISTINCT ?employeeEntry; separator="|") AS ?employees)
WHERE {
  VALUES ?site { %s }
  ?item p:P856 ?siteStatement .
  ?siteStatement ps:P856 ?site ;
                 wikibase:rank ?rank .
  ?item wikibase:sitelinks ?sitelinks .
  BIND(EXISTS { ?item wdt:P31/wdt:P279* wd:Q43229 } AS ?isOrg)
  OPTIONAL { ?item rdfs:label ?enLabel . FILTER(LANG(?enLabel) = "en") }
  OPTIONAL { ?item rdfs:label ?mulLabel . FILTER(LANG(?mulLabel) = "mul") }
  BIND(COALESCE(?enLabel, ?mulLabel) AS ?label)
  OPTIONAL { ?item skos:altLabel ?alias . FILTER(LANG(?alias) IN ("en", "mul")) }
  OPTIONAL { ?item wdt:P571 ?inception . }
  OPTIONAL {
    ?item wdt:P17 ?countryItem .
    ?countryItem rdfs:label ?countryLabel . FILTER(LANG(?countryLabel) IN ("en", "mul"))
    OPTIONAL { ?countryItem wdt:P297 ?countryIso . }
  }
  OPTIONAL { ?item wdt:P5531 ?cikValue . }
  OPTIONAL {
    ?item wdt:P452 ?industry .
    ?industry rdfs:label ?industryLabel . FILTER(LANG(?industryLabel) IN ("en", "mul"))
  }
  OPTIONAL {
    ?item p:P1128 ?employeeStatement .
    ?employeeStatement ps:P1128 ?employeeCount .
    OPTIONAL { ?employeeStatement pq:P585 ?employeeDate . }
    BIND(CONCAT(STR(?employeeCount), "@", COALESCE(STR(?employeeDate), "")) AS ?employeeEntry)
  }
}
GROUP BY ?site ?item ?label ?sitelinks ?rank ?isOrg
"""

RANKS = {
    "http://wikiba.se/ontology#PreferredRank": "preferred",
    "http://wikiba.se/ontology#NormalRank": "normal",
    "http://wikiba.se/ontology#DeprecatedRank": "deprecated",
}
RANK_ORDER = {"preferred": 2, "normal": 1, "deprecated": 0}


@dataclass
class Candidate:
    qid: str
    label: str | None
    aliases: list[str] = field(default_factory=list)
    sitelinks: int = 0
    website_rank: str = "normal"
    is_organization: bool = False
    founded_year: int | None = None
    country: str | None = None
    country_code: str | None = None
    cik: str | None = None
    industries: list[str] = field(default_factory=list)
    employee_count: int | None = None


def url_variants(domain):
    """The forms a website is commonly recorded in: http/https, www or not, trailing slash or not."""
    return [
        f"{scheme}://{host}{slash}"
        for scheme in ("https", "http")
        for host in (domain, f"www.{domain}")
        for slash in ("", "/")
    ]


def build_query(domains):
    values = " ".join(f"<{url}>" for d in domains for url in url_variants(d))
    return QUERY_TEMPLATE % values


class WikidataClient:
    def __init__(self, max_retries=5, base_delay=1.0, sleep=time.sleep):
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
        )
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.sleep = sleep

    def find_candidates(self, domains):
        """Return {domain: [Candidate, ...]} for every domain given. Domains with no match map to []."""
        domains = list(dict.fromkeys(domains))
        candidates = {d: [] for d in domains}

        for start in range(0, len(domains), DOMAINS_PER_QUERY):
            batch = domains[start : start + DOMAINS_PER_QUERY]
            resp = request_with_retries(
                self.session,
                "POST",
                SPARQL_URL,
                sleep=self.sleep,
                max_retries=self.max_retries,
                base_delay=self.base_delay,
                data={"query": build_query(batch)},
            )
            resp.raise_for_status()
            for domain, candidate in parse_results(resp.json()):
                if domain in candidates:
                    candidates[domain].append(candidate)

        return {d: merge_duplicates(c) for d, c in candidates.items()}


def parse_results(data):
    """Yield (domain, Candidate) for each row of a SPARQL JSON response."""
    for row in data["results"]["bindings"]:
        value = lambda key: row.get(key, {}).get("value")  # noqa: E731

        yield normalize_domain(value("site")), Candidate(
            qid=value("item").rsplit("/", 1)[-1],
            label=value("label"),
            aliases=_split(value("aliases")),
            sitelinks=int(value("sitelinks") or 0),
            website_rank=RANKS.get(value("rank"), "normal"),
            is_organization=value("isOrg") == "true",
            founded_year=_year(value("founded")),
            country=value("country"),
            country_code=(value("countryCode") or "").upper() or None,
            cik=value("cik"),
            industries=_split(value("industries")),
            employee_count=latest_employee_count(_split(value("employees"))),
        )


def merge_duplicates(candidates):
    """One item can match several URL variants; keep it once, with its best website rank."""
    best = {}
    for c in candidates:
        current = best.get(c.qid)
        if current is None or RANK_ORDER[c.website_rank] > RANK_ORDER[current.website_rank]:
            best[c.qid] = c
    return list(best.values())


def latest_employee_count(entries):
    """Pick the employee count with the most recent "point in time" date.

    Entries look like "35000@2023-01-31T00:00:00Z", or "35000@" when undated.
    Undated values are only used when there's exactly one value in total,
    because there's no principled way to choose between several undated ones.
    """
    dated, undated = [], []
    for entry in entries:
        count, _, date = entry.partition("@")
        try:
            number = int(float(count))
        except ValueError:
            continue
        (dated if date else undated).append((date, number))

    if dated:
        return max(dated)[1]
    if len(undated) == 1:
        return undated[0][1]
    return None


def _split(text):
    return [part for part in (text or "").split("|") if part]


def _year(timestamp):
    """Wikidata dates look like "2002-01-01T00:00:00Z". BCE dates start with "-" and are ignored."""
    if not timestamp or timestamp.startswith("-"):
        return None
    try:
        return int(timestamp[:4])
    except ValueError:
        return None
