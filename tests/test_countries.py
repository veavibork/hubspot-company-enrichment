import pytest

from enrichment.build_countries import build_table
from enrichment.countries import country_key, to_iso2


@pytest.mark.parametrize(
    "text, expected",
    [
        ("United States", "US"),
        ("USA", "US"),
        ("U.S.A.", "US"),
        ("u.s.", "US"),
        ("United States of America", "US"),
        ("US", "US"),
        ("United Kingdom", "GB"),
        ("UK", "GB"),
        ("GB", "GB"),
        ("Canada", "CA"),
        ("CAN", "CA"),
        ("Australia", "AU"),
    ],
)
def test_to_iso2_resolves_common_spellings(text, expected):
    assert to_iso2(text) == expected


@pytest.mark.parametrize("text", [None, "", "Narnia", "Congo"])
def test_to_iso2_returns_none_for_unknown_or_ambiguous(text):
    assert to_iso2(text) is None


def test_country_key_ignores_case_spaces_and_punctuation():
    assert country_key(" U.S.A. ") == country_key("usa") == "usa"
    assert country_key("United Kingdom") == "unitedkingdom"


def test_build_table_drops_aliases_claimed_by_two_countries():
    rows = [
        ("CD", "COD", "Democratic Republic of the Congo"),
        ("CD", "COD", "Congo"),
        ("CG", "COG", "Republic of the Congo"),
        ("CG", "COG", "Congo"),
    ]

    table, ambiguous = build_table(rows)

    assert table["democraticrepublicofthecongo"] == "CD"
    assert table["cog"] == "CG"
    assert "congo" not in table
    assert ambiguous == {"congo": ["CD", "CG"]}
