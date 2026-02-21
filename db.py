"""Supabase DB integration for AusMoneySaver."""

import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import create_client

from scrapers.base import ProviderResult

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_LEGACY_KEY = os.getenv("SUPABASE_KEY", "")

BANK_PROVIDER_TYPES = {"bank", "banks"}
FINTECH_PROVIDER_TYPES = {"fintech", "fin-tech", "fin tech"}
OFFLINE_PROVIDER_TYPES = {
    "offline",
    "offline_exchange",
    "offline_exchanges",
    "cash_exchange",
    "money_changer",
}
BANK_PROVIDERS = {"anz", "commbank", "nab", "westpac"}
FINTECH_PROVIDERS = {"wise", "remitly", "ofx"}
OFFLINE_PROVIDERS = {
    "unitedcurrency",
    "united currency",
    "travelmoneyoz",
    "travelex",
}


def _resolve_supabase_key() -> str:
    if SUPABASE_SERVICE_ROLE_KEY:
        return SUPABASE_SERVICE_ROLE_KEY
    if SUPABASE_LEGACY_KEY:
        print(
            "[WARN] Using legacy SUPABASE_KEY. "
            "Migrate to SUPABASE_SERVICE_ROLE_KEY for secure write access."
        )
        return SUPABASE_LEGACY_KEY
    return ""


@lru_cache(maxsize=1)
def get_client():
    supabase_key = _resolve_supabase_key()
    if not SUPABASE_URL or not supabase_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env "
            "(SUPABASE_KEY is accepted temporarily for backward compatibility)."
        )
    return create_client(SUPABASE_URL, supabase_key)


def build_run_id(run_id: str | None = None) -> str:
    if run_id:
        return run_id
    env_run_id = os.getenv("SCRAPE_RUN_ID", "").strip()
    if env_run_id:
        return env_run_id
    return datetime.now(timezone.utc).strftime("manual-%Y%m%dT%H%M%SZ")


def _is_legacy_schema_error(error: APIError) -> bool:
    text = str(error).lower()
    return (
        "run_id" in text
        or "uq_rates_run_provider_currency" in text
        or "on_conflict" in text
    )


def _normalize_provider_type(provider_type: str | None, provider: str | None = None) -> str:
    raw = (provider_type or "").strip().lower()
    if raw in BANK_PROVIDER_TYPES:
        return "Bank"
    if raw in FINTECH_PROVIDER_TYPES:
        return "Fintech"
    if raw in OFFLINE_PROVIDER_TYPES:
        return "Offline"
    provider_raw = (provider or "").strip().lower()
    if provider_raw in BANK_PROVIDERS:
        return "Bank"
    if provider_raw in FINTECH_PROVIDERS:
        return "Fintech"
    if provider_raw in OFFLINE_PROVIDERS:
        return "Offline"
    if "bank" in raw:
        return "Bank"
    if "fin" in raw:
        return "Fintech"
    return "Offline"


def _drop_run_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in row.items() if k != "run_id"} for row in rows]


def save_results(results: list[ProviderResult], run_id: str | None = None) -> int:
    """Insert all scraped rates into the exchange_rates table.
    Returns the number of rows inserted."""
    client = get_client()
    effective_run_id = build_run_id(run_id)
    now = datetime.now(timezone.utc).isoformat()

    rows = []
    for r in results:
        for code, rate in r.rates.items():
            rows.append({
                "run_id": effective_run_id,
                "provider": r.provider,
                "provider_type": _normalize_provider_type(r.provider_type, r.provider),
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
    legacy_mode = False
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        if legacy_mode:
            legacy_batch = _drop_run_id(batch)
            client.table("exchange_rates").insert(legacy_batch).execute()
            inserted += len(batch)
            continue

        try:
            client.table("exchange_rates").upsert(
                batch,
                on_conflict="run_id,provider,currency",
                ignore_duplicates=False,
            ).execute()
        except APIError as e:
            if not _is_legacy_schema_error(e):
                raise
            legacy_mode = True
            print(
                "[WARN] Falling back to legacy insert mode. "
                "Apply supabase_setup.sql to enable run_id upserts."
            )
            legacy_batch = _drop_run_id(batch)
            client.table("exchange_rates").insert(legacy_batch).execute()
        inserted += len(batch)

    return inserted


def save_run_summary(
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
    results: list[ProviderResult],
    failures: list[dict[str, str]],
    rows_inserted: int,
    status: str,
) -> None:
    """Persist high-level scrape run diagnostics."""
    if status not in {"success", "partial", "failed"}:
        raise ValueError(f"Invalid status: {status}")

    provider_breakdown: dict[str, dict[str, Any]] = {}
    for item in results:
        provider_breakdown[item.provider] = {
            "provider_type": item.provider_type,
            "currency_count": len(item.rates),
            "timestamp": item.timestamp,
        }

    payload = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "success_count": len(results),
        "failure_count": len(failures),
        "rows_inserted": rows_inserted,
        "status": status,
        "details": {
            "providers": provider_breakdown,
            "failures": failures,
        },
    }

    client = get_client()
    client.table("scrape_runs").upsert(payload, on_conflict="run_id").execute()
