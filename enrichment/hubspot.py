import time

import requests

from enrichment.config import HUBSPOT_API_VERSION, HUBSPOT_BASE_URL, HUBSPOT_BATCH_SIZE
from enrichment.retries import request_with_retries


class HubSpotError(Exception):
    def __init__(self, status, message):
        super().__init__(f"HubSpot API error {status}: {message}")
        self.status = status
        self.message = message


def chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


class HubSpotClient:
    def __init__(self, token, max_retries=5, base_delay=1.0, sleep=time.sleep):
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.sleep = sleep  # injected so tests don't wait

    def _request(self, method, path, **kwargs):
        resp = request_with_retries(
            self.session,
            method,
            f"{HUBSPOT_BASE_URL}{path}",
            sleep=self.sleep,
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            **kwargs,
        )
        if resp.status_code >= 400:
            raise HubSpotError(resp.status_code, _error_message(resp))
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def iter_companies(self, properties, page_size=100):
        path = f"/crm/objects/{HUBSPOT_API_VERSION}/companies"
        params = {"limit": page_size, "properties": ",".join(properties)}

        while True:
            data = self._request("GET", path, params=params)
            yield from data.get("results", [])

            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                return
            params["after"] = after

    def batch_update_companies(self, inputs):
        """inputs: [{"id": record ID, "properties": {...}}]"""
        path = f"/crm/objects/{HUBSPOT_API_VERSION}/companies/batch/update"
        return self._batch(path, inputs)

    def batch_upsert_companies(self, inputs, id_property):
        """inputs: [{"id": value of id_property, "properties": {...}}]; id_property must be unique-valued."""
        path = f"/crm/objects/{HUBSPOT_API_VERSION}/companies/batch/upsert"
        keyed = [{**item, "idProperty": id_property} for item in inputs]
        return self._batch(path, keyed)

    def _batch(self, path, inputs):
        """Returns (results, errors). Partial failures (HTTP 207) arrive in errors, not as exceptions."""
        results, errors = [], []
        for chunk in chunked(inputs, HUBSPOT_BATCH_SIZE):
            data = self._request("POST", path, json={"inputs": chunk})
            results.extend(data.get("results", []))
            errors.extend(data.get("errors", []))
        return results, errors

    def get_company_property_names(self):
        path = f"/crm/properties/{HUBSPOT_API_VERSION}/companies"
        data = self._request("GET", path)
        return {prop["name"] for prop in data.get("results", [])}

    def create_company_property(self, definition):
        path = f"/crm/properties/{HUBSPOT_API_VERSION}/companies"
        return self._request("POST", path, json=definition)


def _error_message(resp):
    try:
        return resp.json().get("message", resp.text)
    except ValueError:
        return resp.text
