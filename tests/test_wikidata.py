from urllib.parse import parse_qs

import responses

from enrichment.wikidata import (
    SPARQL_URL,
    Candidate,
    WikidataClient,
    latest_employee_count,
    merge_duplicates,
    parse_results,
    url_variants,
)

PREFERRED = "http://wikiba.se/ontology#PreferredRank"
NORMAL = "http://wikiba.se/ontology#NormalRank"


def binding(**values):
    return {key: {"value": value} for key, value in values.items()}


SAMPLE_RESPONSE = {
    "results": {
        "bindings": [
            binding(
                site="https://www.wayfair.com/",
                item="http://www.wikidata.org/entity/Q3540193",
                label="Wayfair",
                sitelinks="8",
                rank=NORMAL,
                isOrg="true",
                founded="2002-01-01T00:00:00Z",
                country="United States",
                cik="0001616707",
                aliases="wayfair.com|Wayfair, Inc.",
                industries="e-commerce",
                employees="",
            ),
            binding(
                site="https://www.hubspot.com/",
                item="http://www.wikidata.org/entity/Q4963923",
                label="Brian Halligan",
                sitelinks="5",
                rank=NORMAL,
                isOrg="false",
                aliases="",
                industries="",
                employees="",
            ),
        ]
    }
}


def test_url_variants_cover_scheme_www_and_trailing_slash():
    variants = url_variants("wayfair.com")

    assert len(variants) == 8
    assert "https://www.wayfair.com/" in variants
    assert "http://wayfair.com" in variants


def test_parse_results_builds_candidates_keyed_by_normalized_domain():
    parsed = list(parse_results(SAMPLE_RESPONSE))

    domain, wayfair = parsed[0]
    assert domain == "wayfair.com"
    assert wayfair == Candidate(
        qid="Q3540193",
        label="Wayfair",
        aliases=["wayfair.com", "Wayfair, Inc."],
        sitelinks=8,
        website_rank="normal",
        is_organization=True,
        founded_year=2002,
        country="United States",
        cik="0001616707",
        industries=["e-commerce"],
        employee_count=None,
    )

    domain, halligan = parsed[1]
    assert domain == "hubspot.com"
    assert halligan.is_organization is False


def test_merge_duplicates_keeps_best_website_rank():
    normal = Candidate(qid="Q1", label="Acme", website_rank="normal")
    preferred = Candidate(qid="Q1", label="Acme", website_rank="preferred")
    other = Candidate(qid="Q2", label="Other")

    merged = merge_duplicates([normal, other, preferred])

    assert {c.qid: c.website_rank for c in merged} == {"Q1": "preferred", "Q2": "normal"}


def test_latest_employee_count_uses_most_recent_date():
    entries = ["35000@2019-01-31T00:00:00Z", "79390@2023-01-31T00:00:00Z", "49000@2020-01-31T00:00:00Z"]

    assert latest_employee_count(entries) == 79390


def test_latest_employee_count_prefers_dated_over_undated():
    assert latest_employee_count(["99999@", "8300@2024-12-31T00:00:00Z"]) == 8300


def test_latest_employee_count_single_undated_value_is_used():
    assert latest_employee_count(["4907@"]) == 4907


def test_latest_employee_count_several_undated_values_is_unknown():
    assert latest_employee_count(["4907@", "13301@"]) is None


@responses.activate
def test_find_candidates_returns_every_domain_and_identifies_itself():
    responses.post(SPARQL_URL, json=SAMPLE_RESPONSE)

    found = WikidataClient(sleep=lambda s: None).find_candidates(
        ["wayfair.com", "hubspot.com", "meetdandy.com"]
    )

    assert [c.qid for c in found["wayfair.com"]] == ["Q3540193"]
    assert [c.qid for c in found["hubspot.com"]] == ["Q4963923"]
    assert found["meetdandy.com"] == []

    request = responses.calls[0].request
    assert "github.com/veavibork/hubspot-company-enrichment" in request.headers["User-Agent"]
    query = parse_qs(request.body)["query"][0]
    assert "<https://www.meetdandy.com/>" in query


@responses.activate
def test_find_candidates_retries_when_rate_limited():
    waits = []
    responses.post(SPARQL_URL, status=429, headers={"Retry-After": "5"})
    responses.post(SPARQL_URL, json={"results": {"bindings": []}})

    found = WikidataClient(sleep=waits.append).find_candidates(["wayfair.com"])

    assert found == {"wayfair.com": []}
    assert waits == [5.0]
