"""Supabase DB integration for AusMoneySaver.

Table schema (create in Supabase SQL editor):

    CREATE TABLE exchange_rates (
        id          BIGSERIAL PRIMARY KEY,
        provider    TEXT NOT NULL,
        provider_type TEXT NOT NULL,
        currency    TEXT NOT NULL,
        send_rate   DOUBLE PRECISION,
        receive_rate DOUBLE PRECISION,
        fee         DOUBLE PRECISION,
        scraped_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX idx_rates_currency ON exchange_rates (currency);
    CREATE INDEX idx_rates_provider ON exchange_rates (provider);
    CREATE INDEX idx_rates_scraped  ON exchange_rates (scraped_at DESC);
"""

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

from scrapers.base import ProviderResult

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


def get_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be set in .env file. "
            "Copy .env.example to .env and fill in your Supabase credentials."
        )
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def save_results(results: list[ProviderResult]) -> int:
    """Insert all scraped rates into the exchange_rates table.
    Returns the number of rows inserted."""
    client = get_client()
    now = datetime.now(timezone.utc).isoformat()

    rows = []
    for r in results:
        for code, rate in r.rates.items():
            rows.append({
                "provider": r.provider,
                "provider_type": r.provider_type,
                "currency": code,
                "send_rate": rate.send_rate,
                "receive_rate": rate.receive_rate,
                "fee": rate.fee,
                "scraped_at": now,
            })

    if not rows:
        return 0

    BATCH = 500
    inserted = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        client.table("exchange_rates").insert(batch).execute()
        inserted += len(batch)

    return inserted
