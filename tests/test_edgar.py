import pytest
import responses

from enrichment.edgar import (
    SEC_DATA_URL,
    EdgarClient,
    build_company,
    clean_category,
    format_location,
    latest_annual_revenue,
    normalize_cik,
)

CIK = "0001439725"
SUBMISSIONS_URL = f"{SEC_DATA_URL}/submissions/CIK{CIK}.json"
FACTS_URL = f"{SEC_DATA_URL}/api/xbrl/companyfacts/CIK{CIK}.json"

SUBMISSIONS = {
    "name": "BIODESIX INC",
    "tickers": ["BDSX"],
    "exchanges": ["Nasdaq"],
    "sicDescription": "Services-Medical Laboratories",
    "category": "Non-accelerated filer<br>Smaller reporting company",
    "stateOfIncorporation": "DE",
    "addresses": {"business": {"city": "LOUISVILLE", "stateOrCountry": "CO"}},
}


def fact(val, start, end, form="10-K", fp="FY"):
    return {"val": val, "start": start, "end": end, "form": form, "fp": fp}


FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        fact(49000000, "2023-01-01", "2023-12-31"),
                        fact(88499000, "2025-01-01", "2025-12-31"),
                        fact(23000000, "2025-07-01", "2025-09-30", form="10-Q", fp="Q3"),
                    ]
                }
            }
        }
    }
}


@pytest.mark.parametrize(
    "value, expected",
    [("1439725", CIK), (1439725, CIK), ("0001439725", CIK), ("CIK 1439725", CIK), ("", None), (None, None)],
)
def test_normalize_cik(value, expected):
    assert normalize_cik(value) == expected


def test_build_company_cleans_and_formats_fields():
    company = build_company(CIK, SUBMISSIONS, FACTS)

    assert company.name == "BIODESIX INC"
    assert company.tickers == ["BDSX"]
    assert company.filer_category == "Non-accelerated filer; Smaller reporting company"
    assert company.business_location == "Louisville, CO"
    assert company.state_of_incorporation == "DE"
    assert (company.annual_revenue, company.revenue_fiscal_year) == (88499000, 2025)


def test_private_company_without_financials():
    private = {"name": "Stripe, Inc.", "tickers": [], "exchanges": [], "sicDescription": "",
               "stateOfIncorporation": "DE", "addresses": {"business": {"city": "SAN FRANCISCO", "stateOrCountry": "CA"}}}

    company = build_company("0001691342", private, None)

    assert company.tickers == []
    assert company.sic_description is None
    assert company.annual_revenue is None
    assert company.business_location == "San Francisco, CA"


def test_latest_annual_revenue_ignores_quarters_and_partial_years():
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    fact(100, "2024-01-01", "2024-12-31"),
                    fact(999, "2025-01-01", "2025-03-31", form="10-K", fp="FY"),  # 3 months, mislabeled
                    fact(888, "2025-01-01", "2025-12-31", form="10-Q", fp="FY"),  # not an annual form
                ]}}
            }
        }
    }

    assert latest_annual_revenue(facts) == (100, 2024)


def test_latest_annual_revenue_compares_across_concepts():
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [fact(100, "2022-01-01", "2022-12-31")]}},
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [fact(300, "2024-01-01", "2024-12-31")]}
                },
            }
        }
    }

    assert latest_annual_revenue(facts) == (300, 2024)


def test_latest_annual_revenue_none_without_facts():
    assert latest_annual_revenue(None) is None
    assert latest_annual_revenue({"facts": {}}) is None


def test_clean_category_and_location_helpers():
    assert clean_category("Large accelerated filer") == "Large accelerated filer"
    assert clean_category("") is None
    assert format_location("OTTAWA", None) == "Ottawa"
    assert format_location(None, None) is None


@responses.activate
def test_client_fetches_both_endpoints_with_user_agent():
    responses.get(SUBMISSIONS_URL, json=SUBMISSIONS)
    responses.get(FACTS_URL, json=FACTS)

    client = EdgarClient("test-app test@example.com", sleep=lambda s: None)
    company = client.company("1439725")

    assert company.annual_revenue == 88499000
    assert all(c.request.headers["User-Agent"] == "test-app test@example.com" for c in responses.calls)


@responses.activate
def test_unknown_cik_returns_none():
    responses.get(SUBMISSIONS_URL, status=404)

    assert EdgarClient("ua", sleep=lambda s: None).company(CIK) is None


@responses.activate
def test_company_without_financial_data():
    responses.get(SUBMISSIONS_URL, json=SUBMISSIONS)
    responses.get(FACTS_URL, status=404)

    company = EdgarClient("ua", sleep=lambda s: None).company(CIK)

    assert company.name == "BIODESIX INC"
    assert company.annual_revenue is None


@responses.activate
def test_requests_are_throttled_to_sec_limit():
    responses.get(SUBMISSIONS_URL, json=SUBMISSIONS)
    responses.get(FACTS_URL, json=FACTS)
    waits = []
    now = [100.0]

    client = EdgarClient("ua", sleep=waits.append, clock=lambda: now[0])
    client.company(CIK)

    # Two requests at the same instant: the second waits out the gap.
    assert waits == [pytest.approx(0.12)]


@responses.activate
def test_companies_deduplicates_ciks():
    responses.get(SUBMISSIONS_URL, json=SUBMISSIONS)
    responses.get(FACTS_URL, json=FACTS)

    found = EdgarClient("ua", sleep=lambda s: None).companies(["1439725", "0001439725"])

    assert list(found) == [CIK]
    assert len(responses.calls) == 2
