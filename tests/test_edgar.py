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


@responses.activate
def test_ticker_list_normalizes_ciks():
    from enrichment.edgar import TICKER_LIST_URL

    responses.get(
        TICKER_LIST_URL,
        json={"0": {"cik_str": 1439725, "ticker": "BDSX", "title": "BIODESIX INC"}},
    )

    rows = EdgarClient("ua", sleep=lambda s: None).ticker_list()

    assert rows == [{"cik": CIK, "ticker": "BDSX", "title": "BIODESIX INC"}]


# --- State of incorporation from the annual report cover page --------------

from enrichment.edgar import SEC_ARCHIVES_URL, cover_page_incorporation, latest_annual_report_url  # noqa: E402

COVER_HTML = (
    '<ix:nonNumeric contextRef="c1" name="dei:EntityIncorporationStateCountryCode" '
    'format="ixt-sec:stateprovnameen"><span style="x">Delaware</span></ix:nonNumeric>'
)


def submissions_with_filings(forms):
    return {
        **SUBMISSIONS,
        "stateOfIncorporation": "NY",
        "filings": {
            "recent": {
                "form": forms,
                "accessionNumber": [f"0000000000-26-00000{i}" for i in range(len(forms))],
                "primaryDocument": [f"doc{i}.htm" for i in range(len(forms))],
            }
        },
    }


def test_latest_annual_report_url_skips_other_forms():
    url = latest_annual_report_url(CIK, submissions_with_filings(["8-K", "10-Q", "10-K", "10-K"]))

    assert url == f"{SEC_ARCHIVES_URL}/1439725/000000000026000002/doc2.htm"


def test_no_annual_report_means_no_url():
    assert latest_annual_report_url(CIK, submissions_with_filings(["D", "D"])) is None


@pytest.mark.parametrize(
    "html, expected",
    [
        (COVER_HTML, "Delaware"),
        ('<ix:nonNumeric name="dei:EntityIncorporationStateCountryCode">DE</ix:nonNumeric>', "DE"),
        ("<html>no tag here</html>", None),
        (None, None),
    ],
)
def test_cover_page_incorporation(html, expected):
    assert cover_page_incorporation(html) == expected


@responses.activate
def test_cover_page_overrides_outdated_metadata():
    submissions = submissions_with_filings(["10-K"])
    responses.get(SUBMISSIONS_URL, json=submissions)
    responses.get(FACTS_URL, json=FACTS)
    responses.get(f"{SEC_ARCHIVES_URL}/1439725/000000000026000000/doc0.htm", body=COVER_HTML)

    company = EdgarClient("ua", sleep=lambda s: None).company(CIK)

    assert company.state_of_incorporation == "DE"
    assert company.incorporation_source == "annual report cover page"


@responses.activate
def test_metadata_used_when_there_is_no_annual_report():
    responses.get(SUBMISSIONS_URL, json=submissions_with_filings(["D"]))
    responses.get(FACTS_URL, status=404)

    company = EdgarClient("ua", sleep=lambda s: None).company(CIK)

    assert company.state_of_incorporation == "NY"
    assert company.incorporation_source == "SEC filer metadata"


@responses.activate
def test_cover_page_failure_falls_back_to_metadata_instead_of_crashing():
    responses.get(SUBMISSIONS_URL, json=submissions_with_filings(["10-K"]))
    responses.get(FACTS_URL, json=FACTS)
    url = f"{SEC_ARCHIVES_URL}/1439725/000000000026000000/doc0.htm"
    for _ in range(3):
        responses.get(url, status=403)

    company = EdgarClient("ua", max_retries=2, sleep=lambda s: None).company(CIK)

    assert company.state_of_incorporation == "NY"
    assert company.incorporation_source == "SEC filer metadata"
    assert company.annual_revenue == 88499000


@responses.activate
def test_cover_page_stops_reading_once_the_tag_is_found():
    from enrichment.edgar import MAX_COVER_PAGE_BYTES

    responses.get(SUBMISSIONS_URL, json=submissions_with_filings(["10-K"]))
    responses.get(FACTS_URL, json=FACTS)
    huge_tail = "x" * (MAX_COVER_PAGE_BYTES * 2)
    responses.get(f"{SEC_ARCHIVES_URL}/1439725/000000000026000000/doc0.htm", body=COVER_HTML + huge_tail)

    client = EdgarClient("ua", sleep=lambda s: None)
    text = client._read_cover_page(f"{SEC_ARCHIVES_URL}/1439725/000000000026000000/doc0.htm")

    assert "Delaware" in text
    assert len(text) < len(COVER_HTML) + 70000  # one chunk past the tag, not the whole document
