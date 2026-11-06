import pytest

from enrichment.domains import normalize_domain


@pytest.mark.parametrize(
    "value, expected",
    [
        ("meetdandy.com", "meetdandy.com"),
        ("BIODESIX.COM", "biodesix.com"),
        ("  wayfair.com  ", "wayfair.com"),
        ("www.wayfair.com", "wayfair.com"),
        ("https://www.meetdandy.com/", "meetdandy.com"),
        ("http://biodesix.com/about?ref=x#top", "biodesix.com"),
        ("https://wayfair.com:8443", "wayfair.com"),
        ("meetdandy.com.", "meetdandy.com"),
        ("investors.biodesix.com", "investors.biodesix.com"),
        ("wayfair.co.uk", "wayfair.co.uk"),
    ],
)
def test_normalizes_valid_domains(value, expected):
    assert normalize_domain(value) == expected


@pytest.mark.parametrize(
    "value", [None, "", "   ", "localhost", "http://", "not a domain", "way fair.com"]
)
def test_rejects_values_that_are_not_domains(value):
    assert normalize_domain(value) is None
