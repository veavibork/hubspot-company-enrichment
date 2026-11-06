"""Retrying HTTP requests, shared by the HubSpot and Wikidata clients."""

import random

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def request_with_retries(session, method, url, sleep, max_retries=5, base_delay=1.0, **kwargs):
    """Send a request, retrying on rate limits and server errors.

    Returns the final response, whether or not it succeeded; callers decide
    how to report errors. Other 4xx errors are never retried, because they
    fail the same way every time.
    """
    for attempt in range(max_retries + 1):
        resp = session.request(method, url, timeout=60, **kwargs)

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
    # 1s, 2s, 4s, ... plus jitter, so parallel clients don't retry in lockstep.
    return base_delay * (2**attempt) + random.uniform(0, base_delay)
