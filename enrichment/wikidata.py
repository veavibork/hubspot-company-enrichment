"""Look up companies in Wikidata by their official website.

Wikidata is used only to fetch data; every judgement happens here, in Python:

1. One small SPARQL query finds items whose official website (P856) matches a
   domain, with the website's rank and the item's sitelink count. (~0.5s)
2. The entity API returns labels, aliases and statements for those items, plus
   labels for their industries and countries. (~1s)
3. Whether an item is an organization is decided by walking its types up
   Wikidata's subclass tree here, with a cache. Asking the query service to do
   that walk (wdt:P31/wdt:P279*) took ~30s and ate Wikidata's per-client query
   time budget.
4. A matched item that isn't an organization (often a product, like GitLab's)
   is not used directly, but its "developer" and "owned by" links are followed
   to find the company behind it. Links from people are never followed.

Choosing between candidates is the job of enrichment/matching.py.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field

import requests

from enrichment.countries import to_iso2
from enrichment.domains import normalize_domain
from enrichment.retries import request_with_retries

SPARQL_URL = "https://query.wikidata.org/sparql"
API_URL = "https://www.wikidata.org/w/api.php"

# Wikimedia asks API clients to identify themselves with a contact point.
USER_AGENT = (
    "hubspot-company-enrichment/0.1 "
    "(https://github.com/veavibork/hubspot-company-enrichment)"
)

DOMAINS_PER_QUERY = 25
ENTITIES_PER_REQUEST = 50  # wbgetentities limit

ORGANIZATION = "Q43229"
HUMAN = "Q5"
MAX_CLASS_DEPTH = 10

# Links followed from a non-organization match (e.g. a product) to the company behind it.
FOLLOWED_LINKS = {"P178": "developer", "P127": "owner"}

CANDIDATE_QUERY = """
SELECT ?site ?item ?rank ?sitelinks WHERE {
  VALUES ?site { %s }
  ?item p:P856 ?siteStatement .
  ?siteStatement ps:P856 ?site ;
                 wikibase:rank ?rank .
  ?item wikibase:sitelinks ?sitelinks .
}
"""

RANKS = {
    "http://wikiba.se/ontology#PreferredRank": "preferred",
    "http://wikiba.se/ontology#NormalRank": "normal",
    "http://wikiba.se/ontology#DeprecatedRank": "deprecated",
}
# "linked" means the item wasn't matched by website at all, but reached by following a link.
RANK_ORDER = {"preferred": 2, "normal": 1, "deprecated": 0, "linked": -1}


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
    found_via: str | None = None  # set when reached through a link rather than by website


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
    return CANDIDATE_QUERY % values


class WikidataClient:
    def __init__(self, max_retries=5, base_delay=1.0, sleep=time.sleep):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.sleep = sleep
        self.class_parents = {}  # class QID -> its P279 parents, cached across lookups
        self.timings = defaultdict(float)  # phase -> seconds, for the run report

    def find_candidates(self, domains):
        """Return {domain: [Candidate, ...]} for every domain given. Domains with no match map to []."""
        domains = list(dict.fromkeys(domains))
        candidates = {d: [] for d in domains}

        started = time.perf_counter()
        matches = []
        for start in range(0, len(domains), DOMAINS_PER_QUERY):
            matches.extend(self._search(domains[start : start + DOMAINS_PER_QUERY]))
        self.timings["Wikidata: find candidates"] += time.perf_counter() - started

        entities, labels = self._fetch_details({m["qid"] for m in matches})

        # Products and other non-organizations often name the company behind
        # them. Those links are followed below; people's links never are.
        links = []  # (domain, target QID, how it was found)
        for m in matches:
            entity = entities.get(m["qid"])
            if entity is None or m["domain"] not in candidates:
                continue
            candidate = self._build(
                entity, labels, sitelinks=m["sitelinks"], website_rank=m["rank"]
            )
            candidates[m["domain"]].append(candidate)

            if not candidate.is_organization and not is_person(entity):
                for prop, relation in FOLLOWED_LINKS.items():
                    for target in entity_ids(entity, prop):
                        via = f"{relation} of {candidate.qid} ({candidate.label or 'no label'})"
                        links.append((m["domain"], target, via))

        if links:
            linked_entities, linked_labels = self._fetch_details(
                {target for _, target, _ in links}, with_sitelinks=True
            )
            for domain, target, via in links:
                entity = linked_entities.get(target)
                if entity is None:
                    continue
                candidate = self._build(
                    entity,
                    linked_labels,
                    sitelinks=len(entity.get("sitelinks", {})),
                    website_rank="linked",
                    found_via=via,
                )
                if candidate.is_organization:
                    candidates[domain].append(candidate)

        return {d: merge_duplicates(c) for d, c in candidates.items()}

    def _fetch_details(self, qids, with_sitelinks=False):
        """Fetch entities plus the labels of their industries and countries."""
        started = time.perf_counter()
        props = "labels|aliases|claims" + ("|sitelinks" if with_sitelinks else "")
        entities = self.get_entities(qids, props=props)
        linked = {qid for e in entities.values() for qid in linked_ids(e)}
        labels = {qid: label(e) for qid, e in self.get_entities(linked, props="labels").items()}
        self.timings["Wikidata: fetch details"] += time.perf_counter() - started
        return entities, labels

    def _build(self, entity, labels, sitelinks, website_rank, found_via=None):
        started = time.perf_counter()
        is_org = self.is_organization(instance_types(entity))
        self.timings["Organization check (local)"] += time.perf_counter() - started
        return build_candidate(
            entity,
            labels,
            sitelinks=sitelinks,
            website_rank=website_rank,
            is_organization=is_org,
            found_via=found_via,
        )

    def _search(self, domains):
        resp = self._send(
            "POST",
            SPARQL_URL,
            data={"query": build_query(domains)},
            headers={"Accept": "application/sparql-results+json"},
        )
        return list(parse_search_results(resp.json()))

    def get_entities(self, qids, props):
        """Fetch entities by QID in batches of 50. Returns {qid: entity JSON}."""
        qids = sorted(qids)
        entities = {}
        for start in range(0, len(qids), ENTITIES_PER_REQUEST):
            resp = self._send(
                "GET",
                API_URL,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(qids[start : start + ENTITIES_PER_REQUEST]),
                    "props": props,
                    "languages": "en|mul",
                    "format": "json",
                },
            )
            entities.update(resp.json().get("entities", {}))
        return {qid: e for qid, e in entities.items() if "missing" not in e}

    def is_organization(self, type_qids):
        """True if any type is "organization" or a subclass of it, walking P279 up to MAX_CLASS_DEPTH levels."""
        frontier, seen = set(type_qids), set()
        for _ in range(MAX_CLASS_DEPTH):
            if ORGANIZATION in frontier:
                return True
            seen |= frontier
            unknown = [q for q in frontier if q not in self.class_parents]
            if unknown:
                for qid, entity in self.get_entities(unknown, props="claims").items():
                    self.class_parents[qid] = set(entity_ids(entity, "P279"))
                for qid in unknown:
                    self.class_parents.setdefault(qid, set())
            frontier = {p for q in frontier for p in self.class_parents[q]} - seen
            if not frontier:
                return False
        return False

    def _send(self, method, url, **kwargs):
        resp = request_with_retries(
            self.session,
            method,
            url,
            sleep=self.sleep,
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            **kwargs,
        )
        resp.raise_for_status()
        return resp


# --- Parsing ------------------------------------------------------------------


def parse_search_results(data):
    """Yield {"domain", "qid", "rank", "sitelinks"} for each SPARQL result row."""
    for row in data["results"]["bindings"]:
        yield {
            "domain": normalize_domain(row["site"]["value"]),
            "qid": row["item"]["value"].rsplit("/", 1)[-1],
            "rank": RANKS.get(row["rank"]["value"], "normal"),
            "sitelinks": int(row["sitelinks"]["value"]),
        }


def build_candidate(entity, labels, sitelinks, website_rank, is_organization, found_via=None):
    countries = entity_ids(entity, "P17")
    country = labels.get(countries[0]) if countries else None
    years = [y for y in (_year(v.get("time")) for v in values(entity, "P571")) if y]
    ciks = values(entity, "P5531")

    return Candidate(
        qid=entity["id"],
        label=label(entity),
        aliases=aliases(entity),
        sitelinks=sitelinks,
        website_rank=website_rank,
        is_organization=is_organization,
        founded_year=min(years) if years else None,
        country=country,
        country_code=to_iso2(country),
        cik=ciks[0] if ciks else None,
        industries=[labels[q] for q in entity_ids(entity, "P452") if labels.get(q)],
        employee_count=latest_employee_count(employee_entries(entity)),
        found_via=found_via,
    )


def statements(entity, prop):
    """Usable statements for a property: deprecated ones dropped, preferred ones winning if present."""
    usable = [
        s
        for s in entity.get("claims", {}).get(prop, [])
        if s.get("rank") != "deprecated" and s["mainsnak"].get("snaktype") == "value"
    ]
    preferred = [s for s in usable if s.get("rank") == "preferred"]
    return preferred or usable


def values(entity, prop):
    return [s["mainsnak"]["datavalue"]["value"] for s in statements(entity, prop)]


def entity_ids(entity, prop):
    return [v["id"] for v in values(entity, prop)]


def instance_types(entity):
    return entity_ids(entity, "P31")


def is_person(entity):
    return HUMAN in instance_types(entity)


def linked_ids(entity):
    """Items whose labels we need: industries and countries."""
    return entity_ids(entity, "P452") + entity_ids(entity, "P17")


def label(entity):
    """English label, falling back to "mul" (Wikidata's language-neutral label, which some items, Etsy among them, use instead)."""
    labels = entity.get("labels", {})
    for lang in ("en", "mul"):
        if lang in labels:
            return labels[lang]["value"]
    return None


def aliases(entity):
    found = entity.get("aliases", {})
    return list(dict.fromkeys(a["value"] for lang in ("en", "mul") for a in found.get(lang, [])))


def employee_entries(entity):
    """Employee counts as "count@date" strings; date is empty when the statement has no point in time (P585)."""
    entries = []
    for s in entity.get("claims", {}).get("P1128", []):
        if s.get("rank") == "deprecated" or s["mainsnak"].get("snaktype") != "value":
            continue
        amount = s["mainsnak"]["datavalue"]["value"]["amount"].lstrip("+")
        dates = s.get("qualifiers", {}).get("P585", [])
        date = dates[0].get("datavalue", {}).get("value", {}).get("time", "").lstrip("+") if dates else ""
        entries.append(f"{amount}@{date}")
    return entries


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


def _year(timestamp):
    """Wikidata dates look like "+2002-01-01T00:00:00Z". BCE dates start with "-" and are ignored."""
    if not timestamp or timestamp.startswith("-"):
        return None
    try:
        return int(timestamp.lstrip("+")[:4])
    except ValueError:
        return None
