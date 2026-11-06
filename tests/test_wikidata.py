import json
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from enrichment.wikidata import (
    API_URL,
    SPARQL_URL,
    Candidate,
    WikidataClient,
    build_candidate,
    employee_entries,
    latest_employee_count,
    merge_duplicates,
    parse_search_results,
    statements,
    url_variants,
)

NORMAL = "http://wikiba.se/ontology#NormalRank"


def item(qid):
    return {"value": f"http://www.wikidata.org/entity/{qid}"}


def search_row(site, qid, sitelinks, rank=NORMAL):
    return {
        "site": {"value": site},
        "item": item(qid),
        "rank": {"value": rank},
        "sitelinks": {"value": str(sitelinks)},
    }


def statement(value, rank="normal", qualifiers=None):
    s = {"rank": rank, "mainsnak": {"snaktype": "value", "datavalue": {"value": value}}}
    if qualifiers:
        s["qualifiers"] = qualifiers
    return s


def ref(qid):
    return statement({"id": qid})


WAYFAIR_ENTITY = {
    "id": "Q3540193",
    "labels": {"en": {"value": "Wayfair"}},
    "aliases": {"en": [{"value": "Wayfair, Inc."}]},
    "claims": {
        "P31": [ref("Q4830453")],
        "P571": [statement({"time": "+2002-01-01T00:00:00Z"})],
        "P17": [ref("Q30")],
        "P452": [ref("Q484847")],
        "P5531": [statement("0001616707")],
    },
}

HALLIGAN_ENTITY = {
    "id": "Q4963923",
    "labels": {"en": {"value": "Brian Halligan"}},
    "claims": {"P31": [ref("Q5")]},
}

LABELS = {"Q30": "United States", "Q484847": "e-commerce"}


def test_url_variants_cover_scheme_www_and_trailing_slash():
    variants = url_variants("wayfair.com")

    assert len(variants) == 8
    assert "https://www.wayfair.com/" in variants
    assert "http://wayfair.com" in variants


def test_parse_search_results_normalizes_domains():
    data = {"results": {"bindings": [search_row("https://www.Wayfair.com/", "Q3540193", 8)]}}

    assert list(parse_search_results(data)) == [
        {"domain": "wayfair.com", "qid": "Q3540193", "rank": "normal", "sitelinks": 8}
    ]


def test_build_candidate_reads_entity_statements():
    candidate = build_candidate(
        WAYFAIR_ENTITY, LABELS, sitelinks=8, website_rank="normal", is_organization=True
    )

    assert candidate == Candidate(
        qid="Q3540193",
        label="Wayfair",
        aliases=["Wayfair, Inc."],
        sitelinks=8,
        website_rank="normal",
        is_organization=True,
        founded_year=2002,
        country="United States",
        country_code="US",
        cik="0001616707",
        industries=["e-commerce"],
        employee_count=None,
    )


def test_label_falls_back_to_mul():
    entity = {"id": "Q1353939", "labels": {"mul": {"value": "Etsy"}}, "claims": {}}

    candidate = build_candidate(entity, {}, sitelinks=0, website_rank="normal", is_organization=True)

    assert candidate.label == "Etsy"


def test_statements_drop_deprecated_and_prefer_preferred():
    entity = {
        "claims": {
            "P17": [ref("Q1"), statement({"id": "Q2"}, rank="preferred"), statement({"id": "Q3"}, rank="deprecated")]
        }
    }

    assert [s["mainsnak"]["datavalue"]["value"]["id"] for s in statements(entity, "P17")] == ["Q2"]


def test_employee_entries_read_point_in_time_qualifier():
    entity = {
        "claims": {
            "P1128": [
                statement(
                    {"amount": "+35000"},
                    qualifiers={"P585": [{"datavalue": {"value": {"time": "+2019-01-31T00:00:00Z"}}}]},
                ),
                statement({"amount": "+79390"}),
            ]
        }
    }

    assert employee_entries(entity) == ["35000@2019-01-31T00:00:00Z", "79390@"]


def test_merge_duplicates_keeps_best_website_rank():
    normal = Candidate(qid="Q1", label="Acme", website_rank="normal")
    preferred = Candidate(qid="Q1", label="Acme", website_rank="preferred")
    other = Candidate(qid="Q2", label="Other")

    merged = merge_duplicates([normal, other, preferred])

    assert {c.qid: c.website_rank for c in merged} == {"Q1": "preferred", "Q2": "normal"}


@pytest.mark.parametrize(
    "entries, expected",
    [
        (["35000@2019-01-31T00:00:00Z", "79390@2023-01-31T00:00:00Z", "49000@2020-01-31T00:00:00Z"], 79390),
        (["99999@", "8300@2024-12-31T00:00:00Z"], 8300),
        (["4907@"], 4907),
        (["4907@", "13301@"], None),
        ([], None),
    ],
)
def test_latest_employee_count(entries, expected):
    assert latest_employee_count(entries) == expected


# --- Organization check -------------------------------------------------------


class FakeClassTree(WikidataClient):
    """Serves P279 (subclass of) statements from a dict instead of the network."""

    def __init__(self, parents):
        super().__init__(sleep=lambda s: None)
        self.parents = parents
        self.fetched = []

    def get_entities(self, qids, props):
        self.fetched.append(sorted(qids))
        return {
            q: {"id": q, "claims": {"P279": [ref(p) for p in self.parents.get(q, [])]}}
            for q in qids
        }


TREE = {
    "Q4830453": ["Q43229"],  # business -> organization
    "Q6881511": ["Q4830453"],  # enterprise -> business
    "Q5": ["Q215627"],  # human -> person
    "Q215627": ["Q35120"],  # person -> entity
}


def test_subclass_of_organization_counts():
    assert FakeClassTree(TREE).is_organization(["Q6881511"]) is True


def test_person_is_not_an_organization():
    assert FakeClassTree(TREE).is_organization(["Q5"]) is False


def test_class_parents_are_cached_across_lookups():
    tree = FakeClassTree(TREE)
    tree.is_organization(["Q6881511"])
    calls = len(tree.fetched)

    tree.is_organization(["Q6881511"])

    assert len(tree.fetched) == calls


def test_class_cycles_terminate():
    cyclic = {"Q1": ["Q2"], "Q2": ["Q1"]}

    assert FakeClassTree(cyclic).is_organization(["Q1"]) is False


# --- End to end with faked HTTP -----------------------------------------------


KNOWN_ENTITIES = {
    "Q3540193": WAYFAIR_ENTITY,
    # A person with an employer link, which must never be followed.
    "Q4963923": {**HALLIGAN_ENTITY, "claims": {"P31": [ref("Q5")], "P108": [ref("Q99")]}},
    "Q99": {
        "id": "Q99",
        "labels": {"en": {"value": "Some Employer"}},
        "claims": {"P31": [ref("Q4830453")]},
    },
    # A product whose "developer" link leads to the company.
    "Q16639197": {
        "id": "Q16639197",
        "labels": {"mul": {"value": "GitLab"}},
        "claims": {"P31": [ref("Q35127")], "P178": [ref("Q55589254")]},
    },
    "Q55589254": {
        "id": "Q55589254",
        "labels": {"en": {"value": "GitLab Inc."}},
        "sitelinks": {"enwiki": {}, "dewiki": {}},
        "claims": {"P31": [ref("Q4830453")], "P571": [statement({"time": "+2011-01-01T00:00:00Z"})]},
    },
    "Q30": {"id": "Q30", "labels": {"en": {"value": "United States"}}},
    "Q484847": {"id": "Q484847", "labels": {"en": {"value": "e-commerce"}}},
    "Q4830453": {"id": "Q4830453", "claims": {"P279": [ref("Q43229")]}},
    "Q5": {"id": "Q5", "claims": {}},
    "Q35127": {"id": "Q35127", "claims": {}},
}


def entities_response(request):
    ids = parse_qs(urlparse(request.url).query)["ids"][0].split("|")
    body = {"entities": {q: KNOWN_ENTITIES.get(q, {"id": q, "missing": ""}) for q in ids}}
    return 200, {}, json.dumps(body)


@responses.activate
def test_find_candidates_end_to_end():
    responses.post(
        SPARQL_URL,
        json={
            "results": {
                "bindings": [
                    search_row("https://www.wayfair.com/", "Q3540193", 8),
                    search_row("https://www.hubspot.com/", "Q4963923", 5),
                ]
            }
        },
    )
    responses.add_callback(responses.GET, API_URL, callback=entities_response)

    client = WikidataClient(sleep=lambda s: None)
    found = client.find_candidates(["wayfair.com", "hubspot.com", "meetdandy.com"])

    wayfair = found["wayfair.com"][0]
    assert (wayfair.label, wayfair.is_organization, wayfair.country_code) == ("Wayfair", True, "US")
    assert found["hubspot.com"][0].is_organization is False
    assert found["meetdandy.com"] == []

    sparql_request = responses.calls[0].request
    assert "github.com/veavibork/hubspot-company-enrichment" in sparql_request.headers["User-Agent"]
    assert "<https://www.meetdandy.com/>" in parse_qs(sparql_request.body)["query"][0]
    assert set(client.timings) == {
        "Wikidata: find candidates",
        "Wikidata: fetch details",
        "Organization check (local)",
    }


@responses.activate
def test_follows_product_developer_link_but_never_a_persons_links():
    responses.post(
        SPARQL_URL,
        json={
            "results": {
                "bindings": [
                    search_row("https://gitlab.com/", "Q16639197", 30),
                    search_row("https://www.hubspot.com/", "Q4963923", 5),
                ]
            }
        },
    )
    responses.add_callback(responses.GET, API_URL, callback=entities_response)

    found = WikidataClient(sleep=lambda s: None).find_candidates(["gitlab.com", "hubspot.com"])

    gitlab = {c.qid: c for c in found["gitlab.com"]}
    assert set(gitlab) == {"Q16639197", "Q55589254"}
    company = gitlab["Q55589254"]
    assert company.is_organization is True
    assert company.website_rank == "linked"
    assert company.found_via == "developer of Q16639197 (GitLab)"
    assert company.sitelinks == 2
    assert company.founded_year == 2011

    assert [c.qid for c in found["hubspot.com"]] == ["Q4963923"]


@responses.activate
def test_search_retries_when_rate_limited():
    waits = []
    responses.post(SPARQL_URL, status=429, headers={"Retry-After": "5"})
    responses.post(SPARQL_URL, json={"results": {"bindings": []}})

    found = WikidataClient(sleep=waits.append).find_candidates(["wayfair.com"])

    assert found == {"wayfair.com": []}
    assert waits == [5.0]


@responses.activate
def test_find_by_cik_reverse_lookup():
    responses.post(
        SPARQL_URL,
        json={
            "results": {
                "bindings": [
                    {"cik": {"value": "0001616707"}, "item": item("Q3540193"), "sitelinks": {"value": "8"}}
                ]
            }
        },
    )
    responses.add_callback(responses.GET, API_URL, callback=entities_response)

    found = WikidataClient(sleep=lambda s: None).find_by_cik({"0001616707", "0001439725"})

    assert [c.qid for c in found["0001616707"]] == ["Q3540193"]
    assert found["0001616707"][0].found_via == "SEC CIK 0001616707"
    assert found["0001439725"] == []
    query = parse_qs(responses.calls[0].request.body)["query"][0]
    assert '"0001439725"' in query and '"1439725"' in query  # padded and unpadded forms


def test_build_query_drops_anything_that_is_not_a_normalized_hostname():
    from enrichment.wikidata import build_query

    query = build_query(["wayfair.com", 'evil.com> } SELECT * WHERE { ?s ?p ?o', "WWW.Etsy.com"])

    assert "<https://wayfair.com>" in query
    assert "evil" not in query
    assert "Etsy" not in query
