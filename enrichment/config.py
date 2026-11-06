"""Settings shared across the project."""

import os

from dotenv import load_dotenv

HUBSPOT_BASE_URL = "https://api.hubapi.com"

# HubSpot's date-versioned API. Upgrading is a one-line change here.
HUBSPOT_API_VERSION = "2026-09"

# HubSpot's maximum number of inputs per batch request.
HUBSPOT_BATCH_SIZE = 100


def load_hubspot_token():
    """Read the HubSpot access token from the environment (or .env)."""
    load_dotenv()
    token = os.getenv("HUBSPOT_ACCESS_TOKEN")
    if not token:
        raise SystemExit(
            "HUBSPOT_ACCESS_TOKEN is not set. Copy .env.example to .env and add your token."
        )
    return token
