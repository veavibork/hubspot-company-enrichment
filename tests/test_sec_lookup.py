import pytest

from enrichment.edgar import EdgarCompany
from enrichment.sec_lookup import ciks_for_name, corroborate, index_by_name, state_code

TICKERS = [
    {"cik": "0001439725", "ticker": "BDSX", "title": "BIODESIX INC"},
    {"cik": "0001653482", "ticker": "GTLB", "title": "Gitlab Inc."},
    {"cik": "0001067983", "ticker": "BRK-A", "title": "BERKSHIRE HATHAWAY INC"},
    {"cik": "0001067983", "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
    {"cik": "0000000001", "ticker": "ACM1", "title": "Acme Corp"},
    {"cik": "0000000002", "ticker": "ACM2", "title": "ACME INC"},
]


@pytest.mark.parametrize(
    "text, expected",
    [("Colorado", "CO"), ("colorado", "CO"), ("CO", "CO"), ("New York", "NY"), ("Ontario", None), ("", None), (None, None)],
)
def test_state_code(text, expected):
    assert state_code(text) == expected


def test_index_matches_exact_normalized_names_only():
    index = index_by_name(TICKERS)

    assert ciks_for_name(index, "Biodesix") == ["0001439725"]
    assert ciks_for_name(index, "GitLab") == ["0001653482"]
    assert ciks_for_name(index, "Biodesix Labs") == []  # partial matches never count
    assert ciks_for_name(index, "Dandy") == []


def test_company_with_several_tickers_appears_once():
    index = index_by_name(TICKERS)

    assert ciks_for_name(index, "Berkshire Hathaway") == ["0001067983"]


def test_different_companies_with_the_same_name_are_all_returned():
    index = index_by_name(TICKERS)

    assert ciks_for_name(index, "Acme") == ["0000000001", "0000000002"]


def test_corroborate_by_business_address_or_incorporation():
    record = EdgarCompany(cik="1", name="X", business_region="CA", state_of_incorporation="DE")

    assert corroborate(record, "California") == "HubSpot state CA matches SEC business address"
    assert corroborate(record, "Delaware") == "HubSpot state DE matches SEC state of incorporation"
    assert corroborate(record, "Texas") is None
    assert corroborate(record, None) is None
