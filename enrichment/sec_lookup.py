"""CIK by exact company name in the SEC ticker list, for companies without one from Wikidata."""

from collections import defaultdict

from enrichment.matching import normalize_name

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}


def state_code(state):
    """"Colorado" or "CO" -> "CO". None if it isn't a US state."""
    if not state:
        return None
    text = state.strip()
    if text.upper() in US_STATES.values():
        return text.upper()
    return US_STATES.get(text.lower())


def index_by_name(ticker_list):
    """{normalized title: [CIK, ...]}. A company with several tickers appears once."""
    index = defaultdict(set)
    for row in ticker_list:
        key = normalize_name(row["title"])
        if key:
            index[key].add(row["cik"])
    return {key: sorted(ciks) for key, ciks in index.items()}


def ciks_for_name(index, hubspot_name):
    return index.get(normalize_name(hubspot_name), [])


def corroborate(record, hubspot_state):
    """Return a reason string if HubSpot's state agrees with the SEC record, else None."""
    code = state_code(hubspot_state)
    if not code:
        return None
    if code == record.business_region:
        return f"HubSpot state {code} matches SEC business address"
    if code == record.state_of_incorporation:
        return f"HubSpot state {code} matches SEC state of incorporation"
    return None
