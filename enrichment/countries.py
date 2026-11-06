"""Resolve free-text country values to ISO 3166-1 alpha-2 codes.

The lookup table (data/countries.csv) is generated from Wikidata by
build_countries.py and committed, so runs and tests don't depend on the network.
"""

import csv
import re
from functools import lru_cache
from pathlib import Path

COUNTRIES_CSV = Path(__file__).resolve().parent.parent / "data" / "countries.csv"


def country_key(text):
    """Lowercase and drop everything but letters and digits: "U.S.A." -> "usa"."""
    return re.sub(r"[\W_]", "", text.lower()) if text else ""


@lru_cache(maxsize=1)
def _lookup():
    with open(COUNTRIES_CSV, newline="", encoding="utf-8") as f:
        return {row["key"]: row["iso2"] for row in csv.DictReader(f)}


def to_iso2(text):
    """Return the ISO alpha-2 code for a country name, alias or code, or None if unknown."""
    return _lookup().get(country_key(text))
