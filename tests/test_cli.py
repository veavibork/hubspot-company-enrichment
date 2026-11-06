from enrichment.cli import enriched_values, plan_updates, same_value
from enrichment.wikidata import Candidate

TODAY = "2026-11-06"

WAYFAIR = Candidate(
    qid="Q3540193",
    label="Wayfair",
    is_organization=True,
    founded_year=2002,
    country_code="US",
    industries=["e-commerce"],
)

WAYFAIR_REASONS = "Q3540193 (Wayfair) score 3: +3 name matches"


def company(id_, name, domain, **props):
    return {"id": id_, "properties": {"name": name, "domain": domain, **props}}


def plan(companies, candidates):
    return plan_updates(companies, candidates, today=TODAY)


def test_enriched_values_leaves_out_missing_data():
    assert enriched_values(WAYFAIR) == {
        "wikidata_id": "Q3540193",
        "wikidata_industry": "e-commerce",
        "wikidata_founded_year": "2002",
    }


def test_matched_company_gets_data_and_match_outcome():
    result = plan([company("1", "Wayfair", "wayfair.com")], {"wayfair.com": [WAYFAIR]})

    assert result.updates == [
        {
            "id": "1",
            "properties": {
                "wikidata_id": "Q3540193",
                "wikidata_industry": "e-commerce",
                "wikidata_founded_year": "2002",
                "wikidata_match_status": "matched",
                "wikidata_match_score": "3",
                "wikidata_match_reasons": WAYFAIR_REASONS,
                "wikidata_last_checked": TODAY,
            },
        }
    ]


def test_only_changed_values_are_written():
    companies = [
        company(
            "1",
            "Wayfair",
            "wayfair.com",
            wikidata_id="Q3540193",
            wikidata_founded_year="2002",
            wikidata_match_status="matched",
            wikidata_match_score="3",
            wikidata_match_reasons=WAYFAIR_REASONS,
            wikidata_last_checked="2026-11-05",
        ),
    ]

    result = plan(companies, {"wayfair.com": [WAYFAIR]})

    assert result.updates[0]["properties"] == {
        "wikidata_industry": "e-commerce",
        "wikidata_last_checked": TODAY,
    }
    assert result.changes["Wayfair"]["wikidata_last_checked"] == ("2026-11-05", TODAY)


def test_rerun_on_the_same_day_changes_nothing():
    companies = [
        company(
            "1",
            "Wayfair",
            "wayfair.com",
            wikidata_id="Q3540193",
            wikidata_industry="e-commerce",
            wikidata_founded_year="2002.0",
            wikidata_match_status="matched",
            wikidata_match_score="3",
            wikidata_match_reasons=WAYFAIR_REASONS,
            wikidata_last_checked=TODAY,
        )
    ]

    result = plan(companies, {"wayfair.com": [WAYFAIR]})

    assert result.updates == []
    assert result.unchanged == ["Wayfair"]


def test_unmatched_companies_record_why_but_get_no_data():
    lookalike = Candidate(qid="Q1", label="Unrelated Holdings", is_organization=True)
    package = Candidate(qid="Q2", label="datadog", is_organization=False)
    companies = [
        company("1", "Dandy", "meetdandy.com"),
        company("2", "Mystery", "mystery.com"),
        company("3", "No Website", ""),
        company("4", "Datadog", "datadoghq.com"),
    ]

    result = plan(
        companies,
        {"meetdandy.com": [], "mystery.com": [lookalike], "datadoghq.com": [package]},
    )

    written = {u["id"]: u["properties"] for u in result.updates}
    assert written["1"]["wikidata_match_status"] == "no_item"
    assert written["2"]["wikidata_match_status"] == "ambiguous"
    assert written["2"]["wikidata_match_score"] == "0"
    assert "Q1 (Unrelated Holdings) score 0" in written["2"]["wikidata_match_reasons"]
    assert written["4"]["wikidata_match_status"] == "rejected"
    assert "not an organization" in written["4"]["wikidata_match_reasons"]
    assert not any(key == "wikidata_id" for props in written.values() for key in props)
    assert "3" not in written

    assert result.no_item == ["Dandy"]
    assert [name for name, _ in result.ambiguous] == ["Mystery"]
    assert [name for name, _ in result.rejected] == ["Datadog"]
    assert result.no_domain == ["No Website"]


def test_unmatched_company_clears_stale_score_but_keeps_old_data():
    companies = [
        company("1", "Dandy", "meetdandy.com", wikidata_id="Q999", wikidata_match_score="6"),
    ]

    result = plan(companies, {"meetdandy.com": []})

    written = result.updates[0]["properties"]
    assert written["wikidata_match_score"] == ""
    assert "wikidata_id" not in written


def test_winning_match_is_kept_for_the_audit_trail():
    result = plan([company("1", "Wayfair", "wayfair.com")], {"wayfair.com": [WAYFAIR]})

    assert result.matches["Wayfair"].candidate.qid == "Q3540193"
    assert "+3 name matches" in result.matches["Wayfair"].reasons


def test_domains_are_normalized_before_lookup():
    result = plan([company("1", "Wayfair", "https://www.Wayfair.com/")], {"wayfair.com": [WAYFAIR]})

    assert result.matches["Wayfair"].candidate.qid == "Q3540193"


def test_same_value_compares_numbers_numerically_and_blanks_as_equal():
    assert same_value("2002", "2002")
    assert same_value("2002.0", "2002")
    assert not same_value("2001", "2002")
    assert not same_value(None, "2002")
    assert not same_value("", "Q1")
    assert same_value("e-commerce", "e-commerce")
    assert same_value(None, "")
    assert same_value("", "")
    assert not same_value("6", "")
