"""Free-text country -> ISO alpha-2 code, via data/countries.csv (see build_countries.py)."""

import csv
import re
from functools import lru_cache
from pathlib import Path

COUNTRIES_CSV = Path(__file__).resolve().parent.parent / "data" / "countries.csv"


def country_key(text):
    """ "U.S.A." -> "usa" """
    return re.sub(r"[\W_]", "", text.lower()) if text else ""


@lru_cache(maxsize=1)
def _lookup():
    with open(COUNTRIES_CSV, newline="", encoding="utf-8") as f:
        return {row["key"]: row["iso2"] for row in csv.DictReader(f)}


def to_iso2(text):
    return _lookup().get(country_key(text))
