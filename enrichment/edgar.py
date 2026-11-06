"""Look up companies in SEC EDGAR by CIK (the SEC's company identifier).

Two endpoints per company:
- submissions: name, tickers, exchanges, industry (SIC), filer category,
  state of incorporation and business address. Exists for any SEC filer,
  including private companies that only file Form D when raising money.
- companyfacts: XBRL financial data from filings. Only exists for companies
  that file financial statements, i.e. public ones.

The SEC requires every automated client to identify itself with a contact
email in the User-Agent, and allows at most 10 requests per second.
"""

import time
from dataclasses import dataclass, field
from datetime import date

import requests

from enrichment.retries import request_with_retries

SEC_DATA_URL = "https://data.sec.gov"

# The SEC's limit is 10 requests/second; stay a little under it.
MIN_SECONDS_BETWEEN_REQUESTS = 0.12

# Companies report revenue under different XBRL concepts; checked in this order.
REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]
ANNUAL_FORMS = {"10-K", "20-F", "40-F"}


@dataclass
class EdgarCompany:
    cik: str
    name: str
    tickers: list[str] = field(default_factory=list)
    exchanges: list[str] = field(default_factory=list)
    sic_description: str | None = None
    filer_category: str | None = None
    state_of_incorporation: str | None = None
    business_location: str | None = None
    annual_revenue: int | None = None
    revenue_fiscal_year: int | None = None


def normalize_cik(cik):
    """EDGAR URLs need the CIK as 10 digits: "1616707" -> "0001616707"."""
    digits = "".join(ch for ch in str(cik) if ch.isdigit())
    return digits.zfill(10) if digits else None


class EdgarClient:
    def __init__(self, user_agent, max_retries=5, base_delay=1.0, sleep=time.sleep, clock=time.monotonic):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.sleep = sleep
        self.clock = clock
        self._last_request = None

    def companies(self, ciks):
        """Return {cik: EdgarCompany, or None if the SEC has no such filer} for each CIK."""
        return {cik: self.company(cik) for cik in sorted({normalize_cik(c) for c in ciks if normalize_cik(c)})}

    def company(self, cik):
        cik = normalize_cik(cik)
        submissions = self._get_json(f"{SEC_DATA_URL}/submissions/CIK{cik}.json")
        if submissions is None:
            return None
        facts = self._get_json(f"{SEC_DATA_URL}/api/xbrl/companyfacts/CIK{cik}.json")
        return build_company(cik, submissions, facts)

    def _get_json(self, url):
        """GET with throttling and retries. Returns None on 404."""
        self._throttle()
        resp = request_with_retries(
            self.session,
            "GET",
            url,
            sleep=self.sleep,
            max_retries=self.max_retries,
            base_delay=self.base_delay,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def _throttle(self):
        now = self.clock()
        if self._last_request is not None:
            wait = MIN_SECONDS_BETWEEN_REQUESTS - (now - self._last_request)
            if wait > 0:
                self.sleep(wait)
                now += wait
        self._last_request = now


def build_company(cik, submissions, facts):
    address = submissions.get("addresses", {}).get("business", {})
    revenue = latest_annual_revenue(facts)

    return EdgarCompany(
        cik=cik,
        name=submissions.get("name", ""),
        tickers=submissions.get("tickers") or [],
        exchanges=[e for e in submissions.get("exchanges") or [] if e],
        sic_description=submissions.get("sicDescription") or None,
        filer_category=clean_category(submissions.get("category")),
        state_of_incorporation=submissions.get("stateOfIncorporation") or None,
        business_location=format_location(address.get("city"), address.get("stateOrCountry")),
        annual_revenue=revenue[0] if revenue else None,
        revenue_fiscal_year=revenue[1] if revenue else None,
    )


def latest_annual_revenue(facts):
    """Return (revenue, fiscal year) from the most recent full-year figure in an annual report, or None.

    Only facts from annual forms, marked full-year ("FY"), covering roughly
    twelve months count, so quarterly figures and partial periods are ignored.
    """
    if not facts:
        return None
    gaap = facts.get("facts", {}).get("us-gaap", {})

    best = None
    for concept in REVENUE_CONCEPTS:
        for fact in gaap.get(concept, {}).get("units", {}).get("USD", []):
            if fact.get("form") not in ANNUAL_FORMS or fact.get("fp") != "FY" or not fact.get("start"):
                continue
            days = (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days
            if not 350 <= days <= 380:
                continue
            if best is None or fact["end"] > best["end"]:
                best = fact

    if best is None:
        return None
    return int(best["val"]), int(best["end"][:4])


def clean_category(category):
    """EDGAR returns e.g. "Non-accelerated filer<br>Smaller reporting company"; HTML doesn't belong in a CRM field."""
    if not category:
        return None
    return "; ".join(part.strip() for part in category.split("<br>") if part.strip())


def format_location(city, region):
    """("LOUISVILLE", "CO") -> "Louisville, CO". Region is a US state or an SEC country code."""
    parts = [city.title() if city else None, region or None]
    return ", ".join(p for p in parts if p) or None
