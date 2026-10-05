# SLO Events Finder

Daily job: scrape SLO County event calendars + Instagram flyers, extract with Claude vision,
dedupe, publish phone page to GitHub Pages (https://whynobro.github.io/sloscraper/).

## Guardrails
- Instagram: burner account ONLY, session reuse, run from home PC only. Never from CI/GitHub Actions.
- Repo is public: secrets live only in `.env` (gitignored). Never commit `data/`, session files, `.env`.
- Every listing source isolated: one failing source must never kill the run.
- Seen IG posts (in `posts` table) are never re-sent to Claude.

## Contract
- `slo_scraper/models.py` (Event, Post, CATEGORIES, TOWNS) and `slo_scraper/store.py` (SQLite)
  are the shared contract. Changing a field means updating every component in the same commit.

## Commands
- Install: `pip install -r requirements.txt`
- Tests: `python -m pytest tests/` (scope to tests/, never whole tree)
- Run without IG: `python run.py --no-ig`

## Maintaining this file
Cap: 80 lines. Over cap, move detail to `docs/`. Never raise the cap.
