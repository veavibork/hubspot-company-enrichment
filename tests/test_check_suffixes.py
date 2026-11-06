from enrichment.check_suffixes import unknown_trailing_words


def test_reports_only_unknown_trailing_words_of_multi_word_names():
    names = ["Wayfair, Inc.", "Salesforce.com", "Etsy Ireland", "Notion Labs Inc.", "Stripe", "Acme Holdings"]

    found = unknown_trailing_words(names)

    assert found == {"ireland": ["Etsy Ireland"], "holdings": ["Acme Holdings"]}
