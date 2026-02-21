# AusMoneySaver Backend

Python scrapers for Australian exchange-rate providers.

## What it does

- Scrapes 10 providers (ANZ, CommBank, NAB, Westpac, Wise, Remitly, OFX, United Currency, Travel Money Oz, Travelex)
- Stores normalized rates in Supabase
- Polls every 10 minutes with a freshness gate to avoid unnecessary writes
- Keeps ops checks for freshness, schema health, and data retention

## Required environment variables

Backend write path:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (preferred)
- `SUPABASE_KEY` (legacy fallback only)

Frontend/read-only checks:

- `SUPABASE_ANON_KEY` (or legacy `SUPABASE_KEY`)

Alert email delivery (optional, for `rate_alerts`):

- `RESEND_API_KEY`
- `ALERT_FROM_EMAIL`
- `PUBLIC_SITE_URL`
- `ALERT_COOLDOWN_HOURS` (optional, default `24`)
- `AFFILIATE_LINK_*` (optional provider-specific overrides)

## One-time Supabase setup

1. Open Supabase SQL Editor.
2. Run `supabase_setup.sql`.
3. Confirm these objects exist:
   - `exchange_rates`
   - `latest_exchange_rates`
   - `scrape_runs`
   - `rate_alerts`

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
python scripts/send_rate_alerts.py --dry-run
```

## GitHub Actions workflows

- `scheduled-scrape.yml`: freshness-gated scrape poll + rate alert email dispatch
- `freshness-watchdog.yml`: stale-data check every 30 minutes
- `schema-health.yml`: schema validation every 6 hours
- `db-maintenance.yml`: prune old rows daily
