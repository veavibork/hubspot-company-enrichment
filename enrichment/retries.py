"""Retrying HTTP requests, shared by the HubSpot and Wikidata clients."""

import random

import requests

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
RETRYABLE_ERRORS = (requests.Timeout, requests.ConnectionError)


def request_with_retries(session, method, url, sleep, max_retries=5, base_delay=1.0, **kwargs):
    """Send a request, retrying on rate limits, server errors, timeouts and dropped connections.

    Returns the final response, whether or not it succeeded; callers decide
    how to report errors. Other 4xx errors are never retried, because they
    fail the same way every time. A network error on the last attempt is raised.
    """
    for attempt in range(max_retries + 1):
        try:
            resp = session.request(method, url, timeout=60, **kwargs)
        except RETRYABLE_ERRORS:
            if attempt == max_retries:
                raise
            sleep(backoff(attempt, base_delay))
            continue

        if resp.status_code not in RETRYABLE_STATUSES or attempt == max_retries:
            return resp
        sleep(retry_delay(resp, attempt, base_delay))


def retry_delay(resp, attempt, base_delay):
    """Seconds to wait before retrying: Retry-After if given, else exponential backoff."""
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 60.0)
        except ValueError:
            pass
    return backoff(attempt, base_delay)


def backoff(attempt, base_delay):
    # 1s, 2s, 4s, ... plus jitter, so parallel clients don't retry in lockstep.
    return base_delay * (2**attempt) + random.uniform(0, base_delay)
