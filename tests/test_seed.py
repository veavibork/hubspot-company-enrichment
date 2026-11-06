from enrichment.seed import read_seed_rows


def test_read_seed_rows_normalizes_and_skips_bad_domains(tmp_path):
    csv_file = tmp_path / "companies.csv"
    csv_file.write_text(
        "name,domain\n"
        "Wayfair,https://www.Wayfair.com/\n"
        " Dandy ,meetdandy.com\n"
        "No Domain,\n",
        encoding="utf-8",
    )

    inputs, skipped = read_seed_rows(csv_file)

    assert inputs == [
        {
            "id": "wayfair.com",
            "properties": {
                "name": "Wayfair",
                "domain": "wayfair.com",
                "normalized_domain": "wayfair.com",
            },
        },
        {
            "id": "meetdandy.com",
            "properties": {
                "name": "Dandy",
                "domain": "meetdandy.com",
                "normalized_domain": "meetdandy.com",
            },
        },
    ]
    assert [row["name"] for row in skipped] == ["No Domain"]
