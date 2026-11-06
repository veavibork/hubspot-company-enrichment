"""SEC EDGAR company records by CIK: filer metadata, annual revenue, and the 10-K cover page."""

import re
import time
from dataclasses import dataclass, field
from datetime import date

import requests

from enrichment.retries import request_with_retries
from enrichment.sec_lookup import state_code

SEC_DATA_URL = "https://data.sec.gov"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
TICKER_LIST_URL = "https://www.sec.gov/files/company_tickers.json"

MIN_SECONDS_BETWEEN_REQUESTS = 0.12  # SEC limit is 10/second

# Companies report revenue under different XBRL concepts.
REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]
ANNUAL_FORMS = {"10-K", "20-F", "40-F"}

COVER_TAG = re.compile(
    r'name="dei:EntityIncorporationStateCountryCode"[^>]*>(.*?)</ix:nonNumeric>', re.S | re.I
)
MAX_COVER_PAGE_BYTES = 5_000_000  # the tag sits near the top; stop if it's missing


@dataclass
class EdgarCompany:
    cik: str
    name: str
    tickers: list[str] = field(default_factory=list)
    exchanges: list[str] = field(default_factory=list)
    sic_description: str | None = None
    filer_category: str | None = None
    state_of_incorporation: str | None = None
    incorporation_source: str | None = None
    business_location: str | None = None
    business_region: str | None = None  # US state or SEC country code
    annual_revenue: int | None = None
    revenue_fiscal_year: int | None = None


def normalize_cik(cik):
    """ "1616707" -> "0001616707" """
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

    def ticker_list(self):
        """[{"cik", "ticker", "title"}] for every listed company."""
        data = self._get_json(TICKER_LIST_URL) or {}
        return [
            {"cik": normalize_cik(row["cik_str"]), "ticker": row["ticker"], "title": row["title"]}
            for row in data.values()
        ]

    def companies(self, ciks):
        """{cik: EdgarCompany, or None if the SEC has no such filer}"""
        return {cik: self.company(cik) for cik in sorted({normalize_cik(c) for c in ciks if normalize_cik(c)})}

    def company(self, cik):
        cik = normalize_cik(cik)
        submissions = self._get_json(f"{SEC_DATA_URL}/submissions/CIK{cik}.json")
        if submissions is None:
            return None
        facts = self._get_json(f"{SEC_DATA_URL}/api/xbrl/companyfacts/CIK{cik}.json")
        company = build_company(cik, submissions, facts)

        # Filer metadata is often wrong about incorporation; the 10-K cover page is authoritative.
        url = latest_annual_report_url(cik, submissions)
        if url:
            try:
                stated = cover_page_incorporation(self._read_cover_page(url))
            except requests.RequestException:
                stated = None  # optional: keep the metadata value
            if stated:
                company.state_of_incorporation = state_code(stated) or stated
                company.incorporation_source = "annual report cover page"
        return company

    def _get_json(self, url):
        resp = self._get(url)
        return None if resp is None else resp.json()

    def _read_cover_page(self, url):
        """Stream an annual report only until the incorporation tag has been read."""
        resp = self._get(url, stream=True)
        if resp is None:
            return None
        text = ""
        try:
            for chunk in resp.iter_content(chunk_size=65536):
                text += chunk.decode("utf-8", errors="ignore")
                if COVER_TAG.search(text) or len(text) > MAX_COVER_PAGE_BYTES:
                    break
        finally:
            resp.close()
        return text

    def _get(self, url, **kwargs):
        """None on 404."""
        self._throttle()
        resp = request_with_retries(
            self.session,
            "GET",
            url,
            sleep=self.sleep,
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            **kwargs,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp

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
        incorporation_source="SEC filer metadata" if submissions.get("stateOfIncorporation") else None,
        business_location=format_location(address.get("city"), address.get("stateOrCountry")),
        business_region=address.get("stateOrCountry") or None,
        annual_revenue=revenue[0] if revenue else None,
        revenue_fiscal_year=revenue[1] if revenue else None,
    )


def latest_annual_report_url(cik, submissions):
    # Filings are listed newest first.
    recent = submissions.get("filings", {}).get("recent", {})
    for form, accession, document in zip(
        recent.get("form", []), recent.get("accessionNumber", []), recent.get("primaryDocument", [])
    ):
        if form in ANNUAL_FORMS and document:
            return f"{SEC_ARCHIVES_URL}/{int(cik)}/{accession.replace('-', '')}/{document}"
    return None


def cover_page_incorporation(html):
    """Value of the inline-XBRL cover tag, e.g. "Delaware"; inner formatting tags are stripped."""
    if not html:
        return None
    match = COVER_TAG.search(html)
    if not match:
        return None
    value = " ".join(re.sub(r"<[^>]+>", " ", match.group(1)).split())
    return value or None


def latest_annual_revenue(facts):
    """(revenue, fiscal year) of the latest ~12-month "FY" figure from an annual form, or None."""
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
    """ "Non-accelerated filer<br>Smaller reporting company" -> "...filer; Smaller..." """
    if not category:
        return None
    return "; ".join(part.strip() for part in category.split("<br>") if part.strip())


def format_location(city, region):
    """ ("LOUISVILLE", "CO") -> "Louisville, CO" """
    parts = [city.title() if city else None, region or None]
    return ", ".join(p for p in parts if p) or None
