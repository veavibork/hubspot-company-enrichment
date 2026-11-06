import pytest

from enrichment.matching import choose_candidate, name_score, normalize_name, score_candidate
from enrichment.wikidata import Candidate


def org(qid, label, **kwargs):
    return Candidate(qid=qid, label=label, is_organization=True, **kwargs)


HUBSPOT = {"name": "HubSpot", "founded_year": "2006", "country": "United States"}


def test_person_listing_company_website_is_never_matched():
    company = org("Q5926631", "HubSpot", founded_year=2006, country="United States", country_code="US")
    founder = Candidate(qid="Q4963923", label="Brian Halligan", is_organization=False, sitelinks=50)

    result = choose_candidate([founder, company], HUBSPOT)

    assert result.status == "matched"
    assert result.candidate.qid == "Q5926631"
    assert any("Brian Halligan" in e for e in result.excluded)


def test_only_non_organizations_means_not_found():
    package = Candidate(qid="Q107383131", label="datadog", is_organization=False)

    result = choose_candidate([package], {"name": "Datadog"})

    assert result.status == "not_found"
    assert result.candidate is None


def test_no_candidates_means_not_found():
    assert choose_candidate([], {"name": "Dandy"}).status == "not_found"


def test_evidence_beats_popularity():
    # Notion: the app has far more sitelinks, but it's a product, not the company.
    app = Candidate(qid="Q60747998", label="Notion", is_organization=False, sitelinks=23)
    company = org("Q89269703", "Notion", sitelinks=0)

    result = choose_candidate([app, company], {"name": "Notion"})

    assert result.candidate.qid == "Q89269703"


def test_duplicate_legal_entity_loses_to_better_corroborated_record():
    main = org("Q7858039", "Twilio", founded_year=2008, country="United States", country_code="US", sitelinks=16)
    duplicate = org("Q131884087", "Twilio Inc.", country="United States", country_code="US")

    result = choose_candidate(
        [duplicate, main], {"name": "Twilio", "founded_year": "2008", "country": "United States"}
    )

    assert result.status == "matched"
    assert result.candidate.qid == "Q7858039"


def test_foreign_subsidiary_scores_below_parent():
    parent = org("Q1353939", "Etsy", founded_year=2005, country="United States", country_code="US")
    subsidiary = org("Q131884452", "Etsy Ireland", country="Ireland", country_code="IE")

    result = choose_candidate(
        [subsidiary, parent], {"name": "Etsy", "founded_year": "2005", "country": "United States"}
    )

    assert result.candidate.qid == "Q1353939"


def test_weak_evidence_is_ambiguous():
    unrelated = org("Q1", "Some Holding Company")

    result = choose_candidate([unrelated], {"name": "Dandy"})

    assert result.status == "ambiguous"


def test_exact_tie_is_ambiguous():
    a = org("Q1", "Acme", sitelinks=0)
    b = org("Q2", "Acme", sitelinks=0)

    assert choose_candidate([a, b], {"name": "Acme"}).status == "ambiguous"


def test_sitelinks_break_exact_score_ties():
    a = org("Q1", "Acme", sitelinks=0)
    b = org("Q2", "Acme", sitelinks=5)

    result = choose_candidate([a, b], {"name": "Acme"})

    assert result.status == "matched"
    assert result.candidate.qid == "Q2"


def test_hubspot_signals_only_count_when_hubspot_has_values():
    candidate = org("Q1", "Wayfair", founded_year=2002, country="United States", country_code="US", employee_count=12000)

    scored = score_candidate(candidate, {"name": "Wayfair"})

    assert scored.score == 3
    assert scored.reasons == ["+3 name matches"]


@pytest.mark.parametrize(
    "hubspot_year, expected_points",
    [("2002", 2), ("2003", 2), ("2001", 2), ("2005", -2)],
)
def test_founded_year_tolerates_one_year(hubspot_year, expected_points):
    candidate = org("Q1", "Unrelated Name", founded_year=2002)

    scored = score_candidate(candidate, {"name": "Wayfair", "founded_year": hubspot_year})

    assert scored.score == expected_points


def test_country_disagreement_is_a_small_penalty():
    # Atlassian redomiciled from Australia to the US; one stale field shouldn't sink a match.
    candidate = org("Q757307", "Atlassian", founded_year=2002, country="Australia", country_code="AU")

    result = choose_candidate(
        [candidate], {"name": "Atlassian", "founded_year": "2002", "country": "United States"}
    )

    assert result.status == "matched"
    assert result.best.score == 4


def test_employee_count_only_penalized_when_wildly_off():
    close = org("Q1", "Salesforce", employee_count=35000)
    wild = org("Q2", "Salesforce", employee_count=500)
    company = {"name": "Salesforce", "numberofemployees": "83334"}

    assert score_candidate(close, company).score == 3
    assert score_candidate(wild, company).score == 2


@pytest.mark.parametrize("hubspot_country", ["United Kingdom", "UK", "GB", "G.B.", "Great Britain"])
def test_country_spellings_resolve_to_the_same_iso_code(hubspot_country):
    candidate = org("Q1", "Acme", country="United Kingdom", country_code="GB")

    scored = score_candidate(candidate, {"name": "Acme", "country": hubspot_country})

    assert "+1 country agrees (United Kingdom)" in scored.reasons


@pytest.mark.parametrize("hubspot_country", ["Narnia", "Congo", "England"])
def test_unresolvable_country_gives_no_signal(hubspot_country):
    # Unknown, or ambiguous (two Congos), or not a country in ISO terms (England):
    # none of these should count against the candidate.
    candidate = org("Q1", "Acme", country="United Kingdom", country_code="GB")

    scored = score_candidate(candidate, {"name": "Acme", "country": hubspot_country})

    assert scored.reasons == ["+3 name matches"]


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Wayfair, Inc.", "wayfair"),
        ("Atlassian. Pty Ltd", "atlassian"),
        ("HubSpot Inc", "hubspot"),
        ("Salesforce.com, Inc.", "salesforce"),
        ("Etsy Ireland", "etsy ireland"),
        ("Notion Labs Inc.", "notion labs"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_name(name, expected):
    assert normalize_name(name) == expected


def test_name_score_checks_aliases():
    assert name_score("Wayfair", ["Q3540193 label", "Wayfair, Inc."]) == 3
    assert name_score("Notion", ["Notion Labs Inc."]) == 2
    assert name_score("Dandy", ["Brian Halligan"]) == 0
