# Frederick Population Intelligence Pipeline

This project builds a local SQLite database of Frederick, Maryland public-interest news coverage and the people mentioned in that coverage.

It is designed for a daily workflow:

1. Fetch Frederick-related articles from configured public sources.
2. Extract article text and identify people mentioned.
3. Store person-level metadata such as roles, organizations, addresses, quotes, and article context.
4. Generate an end-of-day report describing notable connections between documented individuals.

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
