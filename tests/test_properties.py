from enrichment.properties import COMPANY_PROPERTIES, ensure_properties


class FakeClient:
    def __init__(self, existing):
        self.existing = set(existing)
        self.created = []

    def get_company_property_names(self):
        return self.existing

    def create_company_property(self, definition):
        self.created.append(definition["name"])


def test_creates_only_missing_properties():
    client = FakeClient(existing={"name", "domain", "normalized_domain", "wikidata_id"})

    missing = ensure_properties(client)

    assert missing == ["wikidata_industry", "wikidata_founded_year", "wikidata_employee_count"]
    assert client.created == missing


def test_creates_nothing_when_all_exist():
    client = FakeClient(existing={d["name"] for d in COMPANY_PROPERTIES})

    assert ensure_properties(client) == []
    assert client.created == []


def test_dry_run_reports_missing_without_creating():
    client = FakeClient(existing=set())

    missing = ensure_properties(client, dry_run=True)

    assert len(missing) == len(COMPANY_PROPERTIES)
    assert client.created == []


def test_normalized_domain_is_unique():
    normalized = next(d for d in COMPANY_PROPERTIES if d["name"] == "normalized_domain")
    assert normalized["hasUniqueValue"] is True
