import pytest
import requests
import responses

from enrichment.retries import request_with_retries

URL = "https://example.com/api"


@responses.activate
def test_retries_after_timeout_then_succeeds():
    waits = []
    responses.get(URL, body=requests.ReadTimeout("slow"))
    responses.get(URL, json={"ok": True})

    resp = request_with_retries(requests.Session(), "GET", URL, sleep=waits.append, max_retries=2)

    assert resp.json() == {"ok": True}
    assert len(waits) == 1


@responses.activate
def test_raises_timeout_after_last_attempt():
    waits = []
    for _ in range(3):
        responses.get(URL, body=requests.ConnectionError("down"))

    with pytest.raises(requests.ConnectionError):
        request_with_retries(requests.Session(), "GET", URL, sleep=waits.append, max_retries=2)

    assert len(waits) == 2
