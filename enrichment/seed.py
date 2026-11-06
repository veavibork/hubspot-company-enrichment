"""Upsert sample companies from a CSV on normalized_domain: python -m enrichment.seed [csv]"""

import csv
import sys

from enrichment.config import load_hubspot_token
from enrichment.domains import normalize_domain
from enrichment.hubspot import HubSpotClient
from enrichment.properties import ensure_properties

DEFAULT_CSV = "data/seed_companies.csv"


def read_seed_rows(path):
    """(upsert inputs, skipped rows without a usable domain)"""
    inputs, skipped = [], []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = normalize_domain(row.get("domain"))
            if not key:
                skipped.append(row)
                continue
            inputs.append(
                {
                    "id": key,
                    "properties": {
                        "name": row["name"].strip(),
                        "domain": key,
                        "normalized_domain": key,
                    },
                }
            )
    return inputs, skipped


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else DEFAULT_CSV

    client = HubSpotClient(load_hubspot_token())

    created = ensure_properties(client)
    if created:
        print(f"Created properties: {', '.join(created)}")

    inputs, skipped = read_seed_rows(path)
    results, errors = client.batch_upsert_companies(inputs, id_property="normalized_domain")

    print(f"Upserted {len(results)} companies from {path}")
    for row in skipped:
        print(f"Skipped (no usable domain): {row}")
    for error in errors:
        print(f"Error: {error.get('message')}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
