from enrichment.cli import enriched_values, plan_updates, same_value
from enrichment.wikidata import Candidate

WAYFAIR = Candidate(
    qid="Q3540193",
    label="Wayfair",
    is_organization=True,
    founded_year=2002,
    country_code="US",
    industries=["e-commerce"],
)


def company(id_, name, domain, **props):
    return {"id": id_, "properties": {"name": name, "domain": domain, **props}}


def test_enriched_values_leaves_out_missing_data():
    assert enriched_values(WAYFAIR) == {
        "wikidata_id": "Q3540193",
        "wikidata_industry": "e-commerce",
        "wikidata_founded_year": "2002",
    }


def test_matched_company_gets_only_changed_values():
    companies = [
        company("1", "Wayfair", "wayfair.com", founded_year="2002", wikidata_id="Q3540193"),
    ]

    plan = plan_updates(companies, {"wayfair.com": [WAYFAIR]})

    assert plan.updates == [
        {
            "id": "1",
            "properties": {"wikidata_industry": "e-commerce", "wikidata_founded_year": "2002"},
        }
    ]
    assert plan.changes["Wayfair"]["wikidata_founded_year"] == (None, "2002")


def test_rerun_with_same_data_changes_nothing():
    companies = [
        company(
            "1",
            "Wayfair",
            "wayfair.com",
            wikidata_id="Q3540193",
            wikidata_industry="e-commerce",
            wikidata_founded_year="2002.0",
        )
    ]

    plan = plan_updates(companies, {"wayfair.com": [WAYFAIR]})

    assert plan.updates == []
    assert plan.unchanged == ["Wayfair"]


def test_unmatched_companies_are_reported_by_reason_not_written():
    lookalike = Candidate(qid="Q1", label="Unrelated Holdings", is_organization=True)
    package = Candidate(qid="Q2", label="datadog", is_organization=False)
    companies = [
        company("1", "Dandy", "meetdandy.com"),
        company("2", "Mystery", "mystery.com"),
        company("3", "No Website", ""),
        company("4", "Datadog", "datadoghq.com"),
    ]

    plan = plan_updates(
        companies,
        {"meetdandy.com": [], "mystery.com": [lookalike], "datadoghq.com": [package]},
    )

    assert plan.updates == []
    assert plan.no_item == ["Dandy"]
    assert [name for name, _ in plan.rejected] == ["Datadog"]
    assert [name for name, _ in plan.ambiguous] == ["Mystery"]
    assert plan.no_domain == ["No Website"]


def test_winning_match_is_kept_for_the_audit_trail():
    plan = plan_updates([company("1", "Wayfair", "wayfair.com")], {"wayfair.com": [WAYFAIR]})

    assert plan.matches["Wayfair"].candidate.qid == "Q3540193"
    assert "+3 name matches" in plan.matches["Wayfair"].reasons


def test_domains_are_normalized_before_lookup():
    companies = [company("1", "Wayfair", "https://www.Wayfair.com/")]

    plan = plan_updates(companies, {"wayfair.com": [WAYFAIR]})

    assert len(plan.updates) == 1


def test_same_value_compares_numbers_numerically():
    assert same_value("2002", "2002")
    assert same_value("2002.0", "2002")
    assert not same_value("2001", "2002")
    assert not same_value(None, "2002")
    assert not same_value("", "Q1")
    assert same_value("e-commerce", "e-commerce")
