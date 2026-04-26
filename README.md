# Frederick Signal Atlas

Frederick Signal Atlas builds a local SQLite database of Frederick, Maryland public-interest news coverage and the people mentioned in that coverage.

It is designed for a daily workflow:

1. Fetch Frederick-related articles from configured public sources.
2. Extract article text and identify people mentioned.
3. Store person-level metadata such as roles, organizations, addresses, quotes, and article context.
4. Generate an end-of-day report describing notable connections between documented individuals.

## Current Behavior

The pipeline now prefers precision over recall.

- If a source article cannot be resolved cleanly, it is skipped rather than indexing a wrapper page.
- If `OPENAI_API_KEY` is not configured, fallback extraction runs in a conservative mode and may store no people for a given day rather than polluting the database with titles, organizations, or event names mistaken for people.
- If an article body changes, or the content extractor changes, the article is automatically re-queued for extraction.
- Person identity is keyed with a disambiguation key (`person_key`) built from the person's name plus the best available organization, address, or home-location context.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
python -m frederick_pipeline daily-run
```

Optional:

```powershell
$env:OPENAI_API_KEY="your-key"
$env:OPENAI_MODEL="gpt-4.1-mini"
```

Without `OPENAI_API_KEY`, the system is still runnable for fetch and storage testing, but the extracted people dataset will usually be sparse. For production-quality person and relationship data, set the API key.

## Output Model

The local SQLite database stores:

- `articles`: fetched article metadata, normalized URL, body text, and extraction state
- `people`: canonical people records with `person_key` disambiguation
- `person_aliases`: alternate names seen in source articles
- `article_people`: article-scoped person mentions with confidence scores and article-local metadata
- `inferred_connections`: same-day inferred links such as co-mentions, shared organizations, and shared addresses

Daily markdown discovery files are written to `data/discoveries/YYYY-MM-DD.md`.

Only higher-confidence article-person records are promoted into reports and connection analysis.

## Source Notes

The default source configuration now focuses on official Frederick city and county feeds plus source-specific local publisher feeds.

- Official feeds generally work well for fetching and archiving.
- Aggregated Google News RSS was removed from the default source list because it frequently resolved to wrapper pages or publisher homepages rather than stable article URLs, which polluted early-stage extraction.
- If you want to add broader media coverage later, prefer source-specific publisher feeds over aggregator wrappers.

## GitHub Actions

The repository includes a scheduled workflow at [.github/workflows/daily-pipeline.yml](C:\Users\xliup\OneDrive\Documents\codex\network\.github\workflows\daily-pipeline.yml).

- It runs every day at `13:05 UTC`.
- In `America/New_York`, that is `9:05 AM EDT` during daylight saving time and `8:05 AM EST` during standard time.
- It can also be triggered manually from the GitHub Actions tab with `workflow_dispatch`.
- The workflow installs dependencies, runs `python -m frederick_pipeline daily-run`, and commits updated `data/` outputs back to `main`.

### Required Repository Configuration

Add this repository secret in GitHub if you want high-quality person extraction:

- `OPENAI_API_KEY`: optional for basic fetch-only runs, recommended for production-quality people and connection data

Optional repository variable:

- `OPENAI_MODEL`: defaults to `gpt-4.1-mini`
