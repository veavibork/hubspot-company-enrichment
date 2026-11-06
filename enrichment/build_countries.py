"""Regenerate data/countries.csv from Wikidata.

    python -m enrichment.build_countries

Every item with an ISO 3166-1 alpha-2 code (P297) contributes its codes,
labels and aliases. An alias that more than one country claims is ambiguous
and left out, so it resolves to "unknown" rather than to the wrong country.
"""

import csv
import time
from collections import defaultdict

import requests

from enrichment.countries import COUNTRIES_CSV, country_key
from enrichment.retries import request_with_retries
from enrichment.wikidata import SPARQL_URL, USER_AGENT

QUERY = """
SELECT ?iso2 ?iso3 ?name WHERE {
  ?country wdt:P297 ?iso2 .
  OPTIONAL { ?country wdt:P298 ?iso3 . }
  {
    ?country rdfs:label ?name . FILTER(LANG(?name) IN ("en", "mul"))
  } UNION {
    ?country skos:altLabel ?name . FILTER(LANG(?name) IN ("en", "mul"))
  }
}
"""


def fetch_rows():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    resp = request_with_retries(session, "POST", SPARQL_URL, sleep=time.sleep, data={"query": QUERY})
    resp.raise_for_status()
    for row in resp.json()["results"]["bindings"]:
        yield (
            row["iso2"]["value"].upper(),
            row.get("iso3", {}).get("value", "").upper(),
            row["name"]["value"],
        )


def build_table(rows):
    """Return ({key: iso2}, {ambiguous key: sorted iso2 codes})."""
    claims = defaultdict(set)
    for iso2, iso3, name in rows:
        for text in (iso2, iso3, name):
            key = country_key(text)
            if key:
                claims[key].add(iso2)

    table = {key: codes.pop() for key, codes in claims.items() if len(codes) == 1}
    ambiguous = {key: sorted(codes) for key, codes in claims.items() if len(codes) > 1}
    return table, ambiguous


def main():
    table, ambiguous = build_table(fetch_rows())

    with open(COUNTRIES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["key", "iso2"])
        for key in sorted(table):
            writer.writerow([key, table[key]])

    print(f"Wrote {len(table)} keys for {len(set(table.values()))} countries to {COUNTRIES_CSV}")
    print(f"Left out {len(ambiguous)} ambiguous keys:")
    for key, codes in sorted(ambiguous.items()):
        print(f"  {key}: {', '.join(codes)}")


if __name__ == "__main__":
    main()
