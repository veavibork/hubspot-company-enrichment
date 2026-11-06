"""Custom company properties this project writes to, and a setup step that creates them."""

GROUP = "companyinformation"

COMPANY_PROPERTIES = [
    {
        "name": "normalized_domain",
        "label": "Normalized Domain",
        "description": "Lowercase domain without scheme, www, or path. Unique key for upserts.",
        "type": "string",
        "fieldType": "text",
        "groupName": GROUP,
        "hasUniqueValue": True,
    },
    {
        "name": "wikidata_id",
        "label": "Wikidata ID",
        "description": "Wikidata item ID (e.g. Q123) matched by official website.",
        "type": "string",
        "fieldType": "text",
        "groupName": GROUP,
    },
    {
        "name": "wikidata_industry",
        "label": "Wikidata Industry",
        "description": "Industry labels from Wikidata, separated by semicolons.",
        "type": "string",
        "fieldType": "text",
        "groupName": GROUP,
    },
    {
        "name": "wikidata_founded_year",
        "label": "Wikidata Founded Year",
        "description": "Year the company was founded, per Wikidata.",
        "type": "number",
        "fieldType": "number",
        "groupName": GROUP,
        # Without this, HubSpot shows thousands separators: "2,011".
        "numberDisplayHint": "unformatted",
    },
    {
        "name": "wikidata_employee_count",
        "label": "Wikidata Employee Count",
        "description": "Most recent employee count reported in Wikidata.",
        "type": "number",
        "fieldType": "number",
        "groupName": GROUP,
    },
    # Match outcome, written for every company checked, so review queues,
    # reports and workflows can be built in HubSpot without code.
    {
        "name": "wikidata_match_status",
        "label": "Wikidata Match Status",
        "description": "Outcome of the last Wikidata match attempt.",
        "type": "enumeration",
        "fieldType": "select",
        "groupName": GROUP,
        "options": [
            {"label": "Matched", "value": "matched", "displayOrder": 0},
            {"label": "Ambiguous, needs review", "value": "ambiguous", "displayOrder": 1},
            {"label": "No Wikidata item with this website", "value": "no_item", "displayOrder": 2},
            {"label": "Only non-organization matches", "value": "rejected", "displayOrder": 3},
        ],
    },
    {
        "name": "wikidata_match_score",
        "label": "Wikidata Match Score",
        "description": "Evidence score of the best candidate (3 or more is required to match).",
        "type": "number",
        "fieldType": "number",
        "groupName": GROUP,
        "numberDisplayHint": "unformatted",
    },
    {
        "name": "wikidata_match_reasons",
        "label": "Wikidata Match Reasons",
        "description": "Why the match was made, or why it wasn't.",
        "type": "string",
        "fieldType": "textarea",
        "groupName": GROUP,
    },
    {
        "name": "wikidata_last_checked",
        "label": "Wikidata Last Checked",
        "description": "Date of the last Wikidata match attempt.",
        "type": "date",
        "fieldType": "date",
        "groupName": GROUP,
    },
]


def ensure_properties(client, definitions=COMPANY_PROPERTIES, dry_run=False):
    """Create any properties that don't exist yet. Safe to run every time.

    Returns the names of properties that were missing (and, unless dry_run,
    have now been created).
    """
    existing = client.get_company_property_names()
    missing = [d for d in definitions if d["name"] not in existing]

    if not dry_run:
        for definition in missing:
            client.create_company_property(definition)

    return [d["name"] for d in missing]
