import json

import pytest
import responses

from enrichment.config import HUBSPOT_API_VERSION, HUBSPOT_BASE_URL
from enrichment.hubspot import HubSpotClient, HubSpotError

COMPANIES_URL = f"{HUBSPOT_BASE_URL}/crm/objects/{HUBSPOT_API_VERSION}/companies"
BATCH_UPDATE_URL = f"{COMPANIES_URL}/batch/update"
BATCH_UPSERT_URL = f"{COMPANIES_URL}/batch/upsert"


@pytest.fixture
def waits():
    return []


@pytest.fixture
def client(waits):
    return HubSpotClient("test-token", max_retries=3, sleep=waits.append)


@responses.activate
def test_sends_bearer_token(client):
    responses.get(COMPANIES_URL, json={"results": []})

    list(client.iter_companies(["domain"]))

    assert responses.calls[0].request.headers["Authorization"] == "Bearer test-token"


@responses.activate
def test_iter_companies_follows_paging_cursor(client):
    responses.get(
        COMPANIES_URL,
        json={"results": [{"id": "1"}], "paging": {"next": {"after": "abc"}}},
    )
    responses.get(COMPANIES_URL, json={"results": [{"id": "2"}]})

    companies = list(client.iter_companies(["domain", "name"]))

    assert [c["id"] for c in companies] == ["1", "2"]
    assert "after" not in responses.calls[0].request.url
    assert "after=abc" in responses.calls[1].request.url
    assert "properties=domain%2Cname" in responses.calls[0].request.url


@responses.activate
def test_retries_after_rate_limit_using_retry_after(client, waits):
    responses.get(COMPANIES_URL, status=429, headers={"Retry-After": "2"}, json={})
    responses.get(COMPANIES_URL, json={"results": [{"id": "1"}]})

    companies = list(client.iter_companies(["domain"]))

    assert [c["id"] for c in companies] == ["1"]
    assert waits == [2.0]


@responses.activate
def test_backs_off_exponentially_without_retry_after(client, waits):
    responses.get(COMPANIES_URL, status=503, json={})
    responses.get(COMPANIES_URL, status=503, json={})
    responses.get(COMPANIES_URL, json={"results": []})

    list(client.iter_companies(["domain"]))

    assert len(waits) == 2
    assert 1.0 <= waits[0] < 2.0
    assert 2.0 <= waits[1] < 3.0


@responses.activate
def test_gives_up_after_max_retries(client, waits):
    for _ in range(4):
        responses.get(COMPANIES_URL, status=429, json={"message": "Rate limited"})

    with pytest.raises(HubSpotError) as exc:
        list(client.iter_companies(["domain"]))

    assert exc.value.status == 429
    assert len(waits) == 3


@responses.activate
def test_does_not_retry_client_errors(client, waits):
    responses.get(COMPANIES_URL, status=401, json={"message": "Invalid token"})

    with pytest.raises(HubSpotError) as exc:
        list(client.iter_companies(["domain"]))

    assert exc.value.status == 401
    assert "Invalid token" in str(exc.value)
    assert waits == []


@responses.activate
def test_batch_update_splits_into_chunks_of_100(client):
    responses.post(BATCH_UPDATE_URL, json={"results": [{"id": "x"}] * 100})
    responses.post(BATCH_UPDATE_URL, json={"results": [{"id": "y"}] * 50})
    inputs = [{"id": str(i), "properties": {"wikidata_id": "Q1"}} for i in range(150)]

    results, errors = client.batch_update_companies(inputs)

    sent = [len(json.loads(call.request.body)["inputs"]) for call in responses.calls]
    assert sent == [100, 50]
    assert len(results) == 150
    assert errors == []


@responses.activate
def test_batch_update_returns_partial_failures(client):
    responses.post(
        BATCH_UPDATE_URL,
        status=207,
        json={
            "results": [{"id": "1"}],
            "errors": [{"message": "Property values were not valid"}],
            "numErrors": 1,
        },
    )
    inputs = [{"id": "1", "properties": {}}, {"id": "2", "properties": {}}]

    results, errors = client.batch_update_companies(inputs)

    assert len(results) == 1
    assert errors == [{"message": "Property values were not valid"}]


@responses.activate
def test_batch_upsert_sets_id_property_on_each_input(client):
    responses.post(BATCH_UPSERT_URL, json={"results": []})

    client.batch_upsert_companies(
        [{"id": "wayfair.com", "properties": {"name": "Wayfair"}}], "normalized_domain"
    )

    sent = json.loads(responses.calls[0].request.body)["inputs"]
    assert sent == [
        {
            "id": "wayfair.com",
            "idProperty": "normalized_domain",
            "properties": {"name": "Wayfair"},
        }
    ]
