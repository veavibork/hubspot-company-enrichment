from enrichment.cli import (
    EdgarResults,
    enriched_values,
    match_companies,
    name_lookup_hits,
    plan_updates,
    same_value,
    verify_name_hits,
    wikidata_ciks,
)
from enrichment.edgar import EdgarCompany
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


def plan(companies, candidates, edgar=None):
    return plan_updates(companies, match_companies(companies, candidates), today=TODAY, edgar=edgar)


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


# --- EDGAR ------------------------------------------------------------------

WAYFAIR_WITH_CIK = Candidate(
    qid="Q3540193", label="Wayfair", is_organization=True, founded_year=2002, cik="1616707"
)

WAYFAIR_SEC = EdgarCompany(
    cik="0001616707",
    name="Wayfair Inc.",
    tickers=["W"],
    exchanges=["NYSE"],
    sic_description="Retail-Catalog & Mail-Order Houses",
    business_location="Boston, MA",
    business_region="MA",
    annual_revenue=12457000000,
    revenue_fiscal_year=2025,
)

BIODESIX_SEC = EdgarCompany(
    cik="0001439725",
    name="BIODESIX INC",
    tickers=["BDSX"],
    state_of_incorporation="DE",
    business_location="Louisville, CO",
    business_region="CO",
)


def edgar_written(companies, candidates, edgar):
    result = plan(companies, candidates, edgar=edgar)
    return {u["id"]: u["properties"] for u in result.updates}, result


def wayfair_edgar(record=WAYFAIR_SEC):
    return EdgarResults(
        records={"0001616707": record}, ciks={"1": ("0001616707", "wikidata_cik")}
    )


def test_wikidata_ciks_are_normalized_and_only_from_matches():
    companies = [company("1", "Wayfair", "wayfair.com"), company("2", "Dandy", "meetdandy.com")]
    results = match_companies(companies, {"wayfair.com": [WAYFAIR_WITH_CIK], "meetdandy.com": []})

    assert wikidata_ciks(results) == {"1": "0001616707"}


def test_edgar_values_written_when_sec_name_agrees():
    written, result = edgar_written(
        [company("1", "Wayfair", "wayfair.com")], {"wayfair.com": [WAYFAIR_WITH_CIK]}, wayfair_edgar()
    )

    props = written["1"]
    assert props["edgar_cik"] == "0001616707"
    assert props["edgar_ticker"] == "W"
    assert props["edgar_annual_revenue"] == "12457000000"
    assert props["edgar_revenue_fiscal_year"] == "2025"
    assert props["edgar_match_status"] == "matched"
    assert props["edgar_match_method"] == "wikidata_cik"
    assert "edgar_state_of_incorporation" not in props  # missing data is left out, not blanked
    assert result.edgar == {"matched (wikidata_cik)": ["Wayfair"]}


def test_edgar_name_conflict_writes_no_data():
    wrong = EdgarCompany(cik="0001616707", name="Totally Different Holdings", tickers=["X"])

    written, result = edgar_written(
        [company("1", "Wayfair", "wayfair.com")], {"wayfair.com": [WAYFAIR_WITH_CIK]}, wayfair_edgar(wrong)
    )

    props = written["1"]
    assert props["edgar_match_status"] == "name_conflict"
    assert props["edgar_name"] == "Totally Different Holdings"
    assert "edgar_ticker" not in props
    assert result.edgar_conflicts == [("Wayfair", "Totally Different Holdings")]


def test_edgar_cik_unknown_to_the_sec():
    written, _ = edgar_written(
        [company("1", "Wayfair", "wayfair.com")], {"wayfair.com": [WAYFAIR_WITH_CIK]}, wayfair_edgar(None)
    )

    assert written["1"]["edgar_match_status"] == "not_found"


def test_no_cik_found():
    written, result = edgar_written(
        [company("1", "Dandy", "meetdandy.com")], {"meetdandy.com": []}, EdgarResults(records={}, ciks={})
    )

    assert written["1"]["edgar_match_status"] == "no_cik"
    assert result.edgar == {"no_cik": ["Dandy"]}


def test_edgar_off_touches_no_edgar_properties():
    written, result = edgar_written(
        [company("1", "Wayfair", "wayfair.com")], {"wayfair.com": [WAYFAIR_WITH_CIK]}, None
    )

    assert not any(key.startswith("edgar_") for key in written["1"])
    assert result.edgar == {}


# --- SEC name lookup (companies without a CIK from Wikidata) -----------------

INDEX = {"biodesix": ["0001439725"], "acme": ["0000000001", "0000000002"], "wayfair": ["0001616707"]}


def test_name_lookup_only_for_checked_companies_without_a_cik():
    companies = [
        company("1", "Wayfair", "wayfair.com"),
        company("2", "Biodesix", "biodesix.com"),
        company("3", "Dandy", "meetdandy.com"),
    ]
    results = match_companies(
        companies, {"wayfair.com": [WAYFAIR_WITH_CIK], "biodesix.com": [], "meetdandy.com": []}
    )

    hits = name_lookup_hits(companies, results, wikidata_ciks(results), INDEX)

    assert hits == {"2": ["0001439725"]}


def test_name_hit_is_verified_by_business_address_state():
    companies = [company("2", "Biodesix", "biodesix.com", state="Colorado")]

    verified, unverified = verify_name_hits(
        companies, {"2": ["0001439725"]}, {"0001439725": BIODESIX_SEC}
    )

    assert verified == {"2": "0001439725"}
    assert unverified == {}


def test_name_hit_is_verified_by_state_of_incorporation():
    # HubSpot recorded GitLab's incorporation state, not its business address.
    gitlab = EdgarCompany(
        cik="0001653482", name="Gitlab Inc.", state_of_incorporation="DE", business_region="CA"
    )
    companies = [company("7", "GitLab", "gitlab.com", state="Delaware")]

    verified, _ = verify_name_hits(companies, {"7": ["0001653482"]}, {"0001653482": gitlab})

    assert verified == {"7": "0001653482"}


def test_name_hit_without_corroboration_is_not_written():
    companies = [company("2", "Biodesix", "biodesix.com", state="Texas")]

    verified, unverified = verify_name_hits(
        companies, {"2": ["0001439725"]}, {"0001439725": BIODESIX_SEC}
    )

    assert verified == {}
    assert "matches neither business address CO nor incorporation DE" in unverified["2"][0]


def test_several_sec_filers_with_the_same_name_is_not_a_match():
    companies = [company("4", "Acme", "acme.com", state="Colorado")]

    verified, unverified = verify_name_hits(companies, {"4": ["0000000001", "0000000002"]}, {})

    assert verified == {}
    assert unverified["4"] == ["2 SEC filers share this name: 0000000001, 0000000002"]


def test_name_lookup_match_is_written_with_its_method():
    companies = [company("2", "Biodesix", "biodesix.com", state="Colorado")]
    edgar = EdgarResults(
        records={"0001439725": BIODESIX_SEC}, ciks={"2": ("0001439725", "sec_name_lookup")}
    )

    written, result = edgar_written(companies, {"biodesix.com": []}, edgar)

    assert written["2"]["edgar_match_method"] == "sec_name_lookup"
    assert written["2"]["edgar_ticker"] == "BDSX"
    assert written["2"]["wikidata_match_status"] == "no_item"
    assert result.edgar == {"matched (sec_name_lookup)": ["Biodesix"]}
