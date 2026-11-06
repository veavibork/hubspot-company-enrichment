# HubSpot Company Enrichment

Enriches HubSpot company records with open data from [Wikidata](https://www.wikidata.org/): founding year, industry, employee count and a stable Wikidata ID, matched by website domain.

The point of the project isn't fetching data; it's **matching it to the right record**. Looking a company up by its website returns people, software products, Python packages and duplicate legal entities alongside the company itself. This tool sorts out which candidate (if any) is really the company, explains every decision, and writes nothing it isn't confident about.

```text
$ python -m enrichment.cli --dry-run
Checking 16 companies against Wikidata...

Would update 13 companies:
  GitLab  [Q55589254 (GitLab Inc.) score 6: +3 name matches; +0 found via developer of Q16639197 (GitLab); +2 founded year agrees (2011); +1 country agrees (United States)]
      wikidata_id: (empty) -> Q55589254
      wikidata_founded_year: (empty) -> 2011
  HubSpot  [Q5926631 (HubSpot) score 6: +3 name matches; +2 founded year agrees (2006); +1 country agrees (United States)]
      wikidata_id: (empty) -> Q5926631
      wikidata_industry: (empty) -> software industry; software as a service; marketing; ...
      wikidata_founded_year: (empty) -> 2006
      wikidata_employee_count: (empty) -> 8246
  ...

Unchanged: 0

No Wikidata item with this website: 3
  Biodesix, Clay, Dandy

Only non-organization matches, rejected: 0

Ambiguous, needs review: 0

Timing (9.1s total):
  HubSpot: properties              0.43s
  HubSpot: read companies          0.28s
  Wikidata: find candidates        0.54s
  Wikidata: fetch details          1.99s
  Organization check (local)       5.85s
  Matching and planning            0.00s
```

## How matching works

Every candidate already shares the company's website. That's necessary but not sufficient, so:

1. **Only organizations count.** Each candidate's types are walked up Wikidata's subclass tree to check whether it is an organization. This excluded, for example, HubSpot's co-founder (his Wikidata entry lists `hubspot.com` as his website) and a Python package named `datadog`.
2. **Products point to their company.** When a website matches a product rather than a company, the product's "developer" and "owned by" links are followed to find the company behind it. Wikidata's `gitlab.com` item describes GitLab the *product*; its developer link leads to **GitLab Inc.**, which is then scored like any other candidate. Links from people are never followed.
3. **Each organization is scored on independent evidence:**

   | Signal | Points |
   |---|---|
   | Name matches HubSpot's (after removing legal suffixes like "Inc.") | +3 exact, +2 partial |
   | Founded year within ±1 of HubSpot's | +2, or −2 if it disagrees |
   | Country matches HubSpot's (compared as ISO codes) | +1, or −1 |
   | Employee count more than 10× off HubSpot's | −1 |
   | Website is Wikidata's preferred / deprecated value | +1 / −1 |

   Signals that compare against HubSpot only count when HubSpot has a value, so the tool works on accounts with or without HubSpot's built-in enrichment.
4. **Sitelinks only break exact ties.** Popularity alone picks the wrong record: the Notion *app* has 23 Wikipedia articles and the Notion *company* has none.
5. **When in doubt, write nothing.** A best score below 3, or an exact tie, is reported as *ambiguous, needs review*. A wrong match does more harm than no match, because it looks trustworthy.

The weights weren't guessed. They came from comparing HubSpot's built-in enrichment with Wikidata field by field for the sample companies (see [Findings](#findings-from-real-data)).

## Design decisions

- **Enrichment writes to its own properties, for now.** Values go into `wikidata_id`, `wikidata_industry`, `wikidata_founded_year` and `wikidata_employee_count`, not into HubSpot's `industry` or `numberofemployees`. This is a staging step, not the end state; see [When enriched data should overwrite the real fields](#when-enriched-data-should-overwrite-the-real-fields).
- **Update by record ID; upsert only where it belongs.** The enrichment run starts from records already in HubSpot, so it updates by ID, which can never create duplicates. Upsert is used only by the seed script, keyed on a custom `normalized_domain` property with unique values enforced. HubSpot's own `domain` property can't be an upsert key, because HubSpot doesn't enforce its uniqueness.
- **Every outcome is recorded on the record.** Each company checked gets `wikidata_match_status` (matched, ambiguous, no Wikidata item, or only non-organization matches), `wikidata_match_score`, `wikidata_match_reasons` and `wikidata_last_checked`. That turns the run's results into ordinary HubSpot data: a saved view of ambiguous companies becomes the review queue, reports show match rates and staleness, and a workflow can assign a review task, all without code. Unmatched companies keep any earlier Wikidata values; their status shows the current outcome.
- **Reruns only write what changed.** Each value is compared with HubSpot's current value, numbers numerically, and unchanged records aren't touched.
- **Company data only.** Wikidata has some fields about people (CEOs, founders); they're deliberately not used. Contact-level enrichment needs a licensed provider and a lawful basis for processing, which is out of scope here.
- **Wikidata fetches; the app evaluates.** One small SPARQL query finds candidates by website, and the entity API returns their details. Running the organization check on Wikidata's server took over 30 seconds and used up the service's per-client query-time budget; doing it locally, with a cache, brought a full run from 40–60 seconds (or a timeout) to under 10.
- **Raw HTTP instead of HubSpot's SDK.** The project calls the API directly with `requests` to show paging, batching, rate limits and retries explicitly. In production I'd likely use [`hubspot-api-client`](https://github.com/HubSpot/hubspot-api-client-python).
- **Retries only where they help.** Rate limits (429), server errors (5xx), timeouts and dropped connections are retried, honoring `Retry-After` when present and otherwise backing off exponentially with jitter. Other 4xx errors fail immediately, because retrying a bad request only wastes rate-limit budget.
- **Partial batch failures are reported, not hidden.** HubSpot answers some batch writes with HTTP 207 (some records succeeded, some failed). Failures are collected per record and listed in the run summary.
- **Pinned API version.** HubSpot calls use the date-versioned API (`2026-09`), set in one place, so upgrading is a deliberate change.
- **Setup is code.** The custom properties are defined in [`enrichment/properties.py`](enrichment/properties.py) and created automatically when missing, so any account gets the same setup with no clicking through settings.

## When enriched data should overwrite the real fields

Teams usually want enrichment to land in the fields people actually use: `industry`, `numberofemployees`, `founded_year`. Writing to separate source-named properties first is deliberate, because deciding *when* a source may overwrite a real field is a business decision, not a technical one, and it should be made per field:

- **Is the field blank or already filled?** Filling blanks is low-risk. Overwriting a value a rep entered is not, because reps often know things no data source does (a recent layoff, a reorganized parent company).
- **How much does this source deserve trust *for this field*?** Founded year agreed between HubSpot and Wikidata for 10 of 11 sample companies, so it's a good candidate for promotion. Employee counts were often stale on one side or the other, so they need a recency check first. Industries use incompatible classification systems, so they need a mapping table before they can be promoted at all.
- **How confident was the match?** A value from a score-6 match with name, founded year and country agreeing deserves more trust than one from a score-3, name-only match. Storing the match score on the record would let promotion rules require a minimum score.
- **Which source wins when sources disagree?** With a second source (SEC EDGAR, planned), each field needs a precedence order: for example, EDGAR for public-company headcount, Wikidata for founded year. A third source makes majority voting possible.
- **Who owns the rule?** Promotion logic fits best in a HubSpot workflow ("if `numberofemployees` is blank and match score ≥ 5, copy `wikidata_employee_count`"), because the operations team can see, adjust and turn it off without a code change. HubSpot's property history also keeps the previous value, so a bad promotion can be traced and reversed.

Keeping each source in its own fields is what makes those decisions possible later: once a source has silently overwritten a field, there's no longer a way to compare it against anything.

## Findings from real data

Building against real records turned up problems no unit test would have:

- **HubSpot's built-in enrichment is useful but imperfect.** It placed GitLab (a fully remote company) in Wilmington, Delaware: its state of incorporation, not where it operates. It also listed Wayfair at 2,000 employees, far below its actual headcount, and classified a dental-technology company as "Facilities Services."
- **A filled field isn't necessarily a correct one.** Every company got a logo from HubSpot, but Etsy's "logo" was HubSpot's generic placeholder image. A 100% logo fill rate, one of them useless.
- **Founded year is the most reliable cross-check.** HubSpot and Wikidata agreed exactly for 10 of 11 companies (the 11th was one year off). Employee counts sometimes differed 2–3× (Salesforce: 83,334 vs 35,000), usually because one source was out of date, so they're only used to rule out wildly wrong matches. Industries use two incompatible classification systems, so they aren't compared at all.
- **Wikidata has its own quirks.** Some items (Etsy's among them) now store their name only under the language-neutral `mul` label, not English, which silently broke name matching until labels fell back from `en` to `mul`. GitLab's product item carries GitLab Inc.'s SEC filing ID and an "alias" of *Zoom*.
- **Country names need a real lookup table.** HubSpot's country field is free text, so "USA", "U.S.A." and "United States" all occur. Countries are compared as ISO codes, using a table generated from Wikidata (1,873 names and aliases for 260 countries). Aliases that belong to more than one country, like "SA" (Saudi Arabia and South Africa) or "Congo", are dropped, and an unrecognized value counts as *no evidence*, never as a mismatch.

## Setup

**Requirements:** Python 3.12+, the [HubSpot CLI](https://developers.hubspot.com/docs/developer-tooling/local-development/hubspot-cli/install-the-cli), and a HubSpot account. A free [developer test account](https://developers.hubspot.com/docs/getting-started/account-types) works.

1. **Install:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
   python -m pip install -r requirements-dev.txt
   ```

2. **Create the HubSpot app.** The app's configuration and scopes are in [`hubspot/`](hubspot/src/app/app-hsmeta.json): company read/write, plus company property read/write so the tool can create its own properties.
   ```bash
   cd hubspot
   hs project upload
   ```
   In HubSpot, open the project, then the app's **Distribution** tab, and install the app into your account. The access token appears there after installing.

3. **Add the token:**
   ```bash
   cp .env.example .env               # then paste your token into .env
   ```

4. **Load sample companies** (optional). This upserts the 16 companies in [`data/seed_companies.csv`](data/seed_companies.csv) on `normalized_domain`, so running it twice doesn't create duplicates:
   ```bash
   python -m enrichment.seed
   ```

## Usage

```bash
python -m enrichment.cli --dry-run      # show what would change; writes nothing
python -m enrichment.cli                # apply the changes
python -m enrichment.cli --limit 5      # only the first 5 companies with a domain
```

Run the dry run first and review the matches and their reasons before applying.

**Tests** fake every HTTP call, so they run in under a second with no HubSpot account or network access:
```bash
python -m pytest
```

**Maintenance tools:**
```bash
python -m enrichment.build_countries    # regenerate data/countries.csv from Wikidata
python -m enrichment.check_suffixes     # list trailing words in real company names that aren't known legal suffixes
```

## Project structure

```text
enrichment/
  cli.py              run orchestration, dry run, report, timing
  matching.py         candidate scoring and selection
  wikidata.py         candidate search, entity details, organization check, product-to-company links
  hubspot.py          HubSpot client: paging, batch update/upsert, properties
  retries.py          retry and backoff, shared by both clients
  properties.py       custom property definitions and setup
  domains.py          domain normalization ("https://www.Acme.com/" -> "acme.com")
  countries.py        country text -> ISO code
  seed.py             load sample companies
  build_countries.py  regenerate the country table
  check_suffixes.py   find legal suffixes missing from the name normalizer
data/
  seed_companies.csv  sample companies
  countries.csv       generated country lookup table
hubspot/              HubSpot app configuration (scopes)
tests/
```

## Limitations and next steps

- **Coverage depends on Wikidata.** In the sample, 13 of 16 companies matched; Biodesix, Clay and Dandy have no Wikidata item with their website. Smaller and private companies are covered less often.
- **SEC EDGAR as a second source (planned).** Wikidata stores many companies' SEC identifiers (CIKs), which can be used to look them up in EDGAR, as a waterfall: domain → Wikidata → EDGAR. A third source also makes it possible to resolve disagreements by majority, which two sources can't. Private companies have CIKs too, from fundraising filings, but EDGAR has far less data on them.
- **Subdomains.** Only a leading `www.` is stripped. Reducing `shop.acme.com` to `acme.com` correctly requires the Public Suffix List (to avoid breaking domains like `acme.co.uk`).
- **Class tree cache.** The organization check is now the slowest step (~5s). Caching Wikidata's class tree between runs would make reruns near-instant.
- **Scale.** Built and tested at tens of records. For tens of thousands, the next steps would be client-side throttling to stay under HubSpot's burst limit, resumable runs, and incremental runs that skip recently checked companies.

## Data and licensing

Wikidata content is available under [CC0](https://creativecommons.org/publicdomain/zero/1.0/) (public domain). The tool identifies itself to Wikidata with a descriptive User-Agent, as Wikimedia's API policy asks. The sample companies are public companies' names and websites; no personal data is used or stored.

The code is released under the [MIT License](LICENSE).
