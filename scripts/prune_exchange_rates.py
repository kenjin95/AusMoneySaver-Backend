"""Prune old exchange rate data from Supabase."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from postgrest.exceptions import APIError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db import get_client


def _is_missing_table_error(error: APIError) -> bool:
    return "404" in str(error)


def count_older_than(client, table: str, column: str, cutoff_iso: str) -> int | None:
    try:
        response = (
            client.table(table)
            .select("*", count="exact", head=True)
            .lt(column, cutoff_iso)
            .execute()
        )
    except APIError as e:
        if _is_missing_table_error(e):
            return None
        raise
    return response.count or 0


def delete_older_than(client, table: str, column: str, cutoff_iso: str) -> int | None:
    try:
        response = (
            client.table(table)
            .delete(count="exact", returning="minimal")
            .lt(column, cutoff_iso)
            .execute()
        )
    except APIError as e:
        if _is_missing_table_error(e):
            return None
        raise
    return response.count or 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="Retention for exchange_rates.")
    parser.add_argument(
        "--run-days",
        type=int,
        default=180,
        help="Retention for scrape_runs.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show counts only.")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    rates_cutoff = (now - timedelta(days=args.days)).isoformat()
    runs_cutoff = (now - timedelta(days=args.run_days)).isoformat()
    client = get_client()

    rates_to_delete = count_older_than(client, "exchange_rates", "scraped_at", rates_cutoff)
    runs_to_delete = count_older_than(client, "scrape_runs", "completed_at", runs_cutoff)

    print(f"Now (UTC): {now.isoformat()}")
    print(f"exchange_rates cutoff: {rates_cutoff}")
    print(f"scrape_runs cutoff: {runs_cutoff}")
    print(f"exchange_rates rows older than cutoff: {rates_to_delete}")
    if runs_to_delete is None:
        print("scrape_runs table not found yet; skipping scrape_runs pruning.")
    else:
        print(f"scrape_runs rows older than cutoff: {runs_to_delete}")

    if args.dry_run:
        print("Dry run mode: no rows deleted.")
        return 0

    deleted_rates = delete_older_than(client, "exchange_rates", "scraped_at", rates_cutoff)
    deleted_runs = delete_older_than(client, "scrape_runs", "completed_at", runs_cutoff)

    print(f"Deleted exchange_rates rows: {deleted_rates}")
    if deleted_runs is None:
        print("scrape_runs table not found; skipped.")
    else:
        print(f"Deleted scrape_runs rows: {deleted_runs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
