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
    },
    {
        "name": "wikidata_employee_count",
        "label": "Wikidata Employee Count",
        "description": "Most recent employee count reported in Wikidata.",
        "type": "number",
        "fieldType": "number",
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
