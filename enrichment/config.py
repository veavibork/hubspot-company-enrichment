import os

from dotenv import load_dotenv

HUBSPOT_BASE_URL = "https://api.hubapi.com"
HUBSPOT_API_VERSION = "2026-09"
HUBSPOT_BATCH_SIZE = 100  # HubSpot's per-request maximum


def load_sec_user_agent():
    """None if unset; EDGAR is then skipped."""
    load_dotenv()
    return os.getenv("SEC_USER_AGENT") or None


def load_hubspot_token():
    load_dotenv()
    token = os.getenv("HUBSPOT_ACCESS_TOKEN")
    if not token:
        raise SystemExit(
            "HUBSPOT_ACCESS_TOKEN is not set. Copy .env.example to .env and add your token."
        )
    return token
