"""A small HubSpot CRM client for company records.

Covers only what this project needs: paging through companies, reading and
creating company properties, and batch update/upsert. Every request goes
through _request(), which retries on rate limits and server errors.
"""

import random
import time

import requests

from enrichment.config import HUBSPOT_API_VERSION, HUBSPOT_BASE_URL, HUBSPOT_BATCH_SIZE

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class HubSpotError(Exception):
    """A HubSpot request failed and won't be retried."""

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
        # Injected so tests can skip real waiting.
        self.sleep = sleep

    def _request(self, method, path, **kwargs):
        url = f"{HUBSPOT_BASE_URL}{path}"

        for attempt in range(self.max_retries + 1):
            resp = self.session.request(method, url, timeout=30, **kwargs)

            if resp.status_code not in RETRYABLE_STATUSES:
                break
            if attempt == self.max_retries:
                break
            self.sleep(self._retry_delay(resp, attempt))

        if resp.status_code >= 400:
            raise HubSpotError(resp.status_code, _error_message(resp))
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def _retry_delay(self, resp, attempt):
        """Seconds to wait before retrying: Retry-After if given, else exponential backoff."""
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        # 1s, 2s, 4s, ... plus jitter, so parallel clients don't retry in lockstep.
        return self.base_delay * (2**attempt) + random.uniform(0, self.base_delay)

    # --- Companies -----------------------------------------------------------

    def iter_companies(self, properties, page_size=100):
        """Yield every company, following HubSpot's cursor paging."""
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
        """Update companies by record ID. inputs: [{"id": ..., "properties": {...}}]"""
        path = f"/crm/objects/{HUBSPOT_API_VERSION}/companies/batch/update"
        return self._batch(path, inputs)

    def batch_upsert_companies(self, inputs, id_property):
        """Create or update companies matched on a unique-value property.

        inputs: [{"id": <value of id_property>, "properties": {...}}]
        """
        path = f"/crm/objects/{HUBSPOT_API_VERSION}/companies/batch/upsert"
        keyed = [{**item, "idProperty": id_property} for item in inputs]
        return self._batch(path, keyed)

    def _batch(self, path, inputs):
        """Send inputs in chunks. Returns (results, errors) across all chunks.

        A 207 response means some inputs succeeded and some failed; those
        failures come back in "errors" rather than as an exception.
        """
        results, errors = [], []
        for chunk in chunked(inputs, HUBSPOT_BATCH_SIZE):
            data = self._request("POST", path, json={"inputs": chunk})
            results.extend(data.get("results", []))
            errors.extend(data.get("errors", []))
        return results, errors

    # --- Properties ----------------------------------------------------------

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
