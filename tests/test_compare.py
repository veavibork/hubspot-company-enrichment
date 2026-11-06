from enrichment.compare import (
    NOT_COMPARABLE,
    compare_founded,
    compare_location,
    compare_numbers,
    compare_public,
)


def names(comparison, outcome):
    return [name for name, _ in comparison.outcomes.get(outcome, [])]


def test_public_private_agreement():
    rows = [
        ("Wayfair", {"is_public": "true", "edgar_match_status": "matched", "edgar_ticker": "W"}),
        ("Stripe", {"is_public": "false", "edgar_match_status": "matched"}),
        ("Oops", {"is_public": "false", "edgar_match_status": "matched", "edgar_ticker": "OOPS"}),
        ("Dandy", {"is_public": "false", "edgar_match_status": "no_cik"}),
    ]

    c = compare_public(rows)

    assert names(c, "agree") == ["Wayfair", "Stripe"]
    assert names(c, "disagree") == ["Oops"]
    assert names(c, NOT_COMPARABLE) == ["Dandy"]
    assert c.compared == 3


def test_location_distinguishes_business_address_from_incorporation():
    rows = [
        ("Biodesix", {"state": "Colorado", "edgar_business_location": "Louisville, CO", "edgar_state_of_incorporation": "DE"}),
        ("GitLab", {"state": "Delaware", "edgar_business_location": "San Francisco, CA", "edgar_state_of_incorporation": "DE"}),
        ("Wrong", {"state": "Texas", "edgar_business_location": "Boston, MA", "edgar_state_of_incorporation": "DE"}),
        ("Shopify", {"state": "Ontario", "edgar_business_location": "Ottawa", "edgar_state_of_incorporation": "Canada"}),
    ]

    c = compare_location(rows)

    assert names(c, "HubSpot matches business address") == ["Biodesix"]
    assert names(c, "HubSpot matches state of incorporation only") == ["GitLab"]
    assert names(c, "HubSpot matches neither") == ["Wrong"]
    assert names(c, NOT_COMPARABLE) == ["Shopify"]


def test_founded_year_buckets():
    rows = [
        ("A", {"founded_year": "2002", "wikidata_founded_year": "2002"}),
        ("B", {"founded_year": "2011", "wikidata_founded_year": "2012"}),
        ("C", {"founded_year": "1990", "wikidata_founded_year": "2000"}),
        ("D", {"founded_year": "2016"}),
    ]

    c = compare_founded(rows)

    assert names(c, "same year") == ["A"]
    assert names(c, "1 year apart") == ["B"]
    assert names(c, "more than 1 year apart") == ["C"]
    assert names(c, NOT_COMPARABLE) == ["D"]


def test_number_comparison_buckets_by_ratio():
    rows = [
        ("Close", {"numberofemployees": "8882", "wikidata_employee_count": "8246"}),
        ("Apart", {"numberofemployees": "83334", "wikidata_employee_count": "35000"}),
        ("Far", {"numberofemployees": "2000", "wikidata_employee_count": "12000"}),
    ]

    c = compare_numbers(rows, "Employees", "", "numberofemployees", "wikidata_employee_count", "Wikidata")

    assert names(c, "within 10%") == ["Close"]
    assert names(c, "1.5-3x apart") == ["Apart"]
    assert names(c, "more than 3x apart") == ["Far"]
