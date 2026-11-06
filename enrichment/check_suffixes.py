"""Report trailing words in real company names that aren't in NAME_SUFFIXES.

    python -m enrichment.check_suffixes

Looks at HubSpot company names plus the labels and aliases of every Wikidata
organization matched by domain. Use the output to decide, word by word,
whether NAME_SUFFIXES is missing a genuine legal form. It changes nothing.
"""

import re
from collections import defaultdict

from enrichment.config import load_hubspot_token
from enrichment.domains import normalize_domain
from enrichment.hubspot import HubSpotClient
from enrichment.matching import NAME_SUFFIXES
from enrichment.wikidata import WikidataClient


def unknown_trailing_words(names):
    """Return {word: [names ending in it]} for multi-word names whose last word isn't a known suffix."""
    found = defaultdict(list)
    for name in names:
        words = re.sub(r"[^\w\s]", " ", name.lower()).split()
        if len(words) > 1 and words[-1] not in NAME_SUFFIXES:
            found[words[-1]].append(name)
    return found


def main():
    hubspot = HubSpotClient(load_hubspot_token())
    companies = list(hubspot.iter_companies(["name", "domain"]))

    names = [c["properties"]["name"] for c in companies if c["properties"].get("name")]
    domains = [normalize_domain(c["properties"].get("domain")) for c in companies]

    candidates = WikidataClient().find_candidates([d for d in domains if d])
    for found in candidates.values():
        for c in found:
            if c.is_organization:
                names.extend(n for n in [c.label, *c.aliases] if n)

    unknown = unknown_trailing_words(set(names))
    print(f"Checked {len(set(names))} names. Trailing words not in NAME_SUFFIXES:")
    for word, examples in sorted(unknown.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print(f"  {word:<15} {len(examples):>3}  e.g. {', '.join(sorted(examples)[:3])}")


if __name__ == "__main__":
    main()
