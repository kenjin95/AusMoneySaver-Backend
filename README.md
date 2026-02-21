# AusMoneySaver Backend

Python scrapers for Australian exchange-rate providers.

## What it does

- Scrapes 6 providers (ANZ, CommBank, Wise, Remitly, United Currency, Travel Money Oz)
- Stores normalized rates in Supabase
- Runs every 30 minutes with GitHub Actions
- Keeps ops checks for freshness, schema health, and data retention

## Required environment variables

Backend write path:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (preferred)
- `SUPABASE_KEY` (legacy fallback only)

Frontend/read-only checks:

- `SUPABASE_ANON_KEY` (or legacy `SUPABASE_KEY`)

## One-time Supabase setup

1. Open Supabase SQL Editor.
2. Run `supabase_setup.sql`.
3. Confirm these objects exist:
   - `exchange_rates`
   - `latest_exchange_rates`
   - `scrape_runs`

## Local run

```bash
pip install -r requirements.txt
python main.py --save --min-success-providers 5 --allow-partial-success
```

Useful ops commands:

```bash
python scripts/check_db_schema.py
python scripts/check_data_freshness.py --threshold-minutes 120
python scripts/prune_exchange_rates.py --days 60 --run-days 180 --dry-run
```

## GitHub Actions workflows

- `scheduled-scrape.yml`: scrape + save every 30 minutes
- `freshness-watchdog.yml`: stale-data check every 30 minutes
- `schema-health.yml`: schema validation every 6 hours
- `db-maintenance.yml`: prune old rows daily
