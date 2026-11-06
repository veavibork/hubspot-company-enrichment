import random

import requests

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
RETRYABLE_ERRORS = (requests.Timeout, requests.ConnectionError)


def request_with_retries(session, method, url, sleep, max_retries=5, base_delay=1.0, **kwargs):
    """Returns the final response even if it failed; callers decide how to report it."""
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
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 60.0)
        except ValueError:
            pass
    return backoff(attempt, base_delay)


def backoff(attempt, base_delay):
    # Jitter keeps clients rate-limited together from retrying together.
    return base_delay * (2**attempt) + random.uniform(0, base_delay)
