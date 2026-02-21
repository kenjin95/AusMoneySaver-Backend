"""Normalize legacy provider aliases in Supabase tables."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from postgrest.exceptions import APIError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db import get_client


def _is_unique_violation(error: APIError) -> bool:
    text = str(error).lower()
    return "duplicate key value violates unique constraint" in text


def _count_provider(client, provider: str) -> int:
    response = (
        client.table("exchange_rates")
        .select("*", count="exact", head=True)
        .eq("provider", provider)
        .execute()
    )
    return response.count or 0


def _iter_alias_ids(client, alias: str, batch_size: int = 1000):
    offset = 0
    while True:
        rows = (
            client.table("exchange_rates")
            .select("id")
            .eq("provider", alias)
            .order("id")
            .range(offset, offset + batch_size - 1)
            .execute()
            .data
            or []
        )
        if not rows:
            break
        for row in rows:
            yield row["id"]
        if len(rows) < batch_size:
            break
        offset += batch_size


def _rowwise_fallback(client, alias: str, canonical: str, dry_run: bool) -> tuple[int, int]:
    updated = 0
    deleted = 0
    for row_id in _iter_alias_ids(client, alias):
        if dry_run:
            updated += 1
            continue
        try:
            response = (
                client.table("exchange_rates")
                .update({"provider": canonical, "provider_type": "Offline"}, count="exact")
                .eq("id", row_id)
                .execute()
            )
            updated += response.count or 0
        except APIError as e:
            if not _is_unique_violation(e):
                raise
            # A canonical row already exists for the same unique key.
            response = (
                client.table("exchange_rates")
                .delete(count="exact", returning="minimal")
                .eq("id", row_id)
                .execute()
            )
            deleted += response.count or 0
    return updated, deleted


def normalize_provider_alias(
    client,
    alias: str,
    canonical: str,
    canonical_type: str,
    dry_run: bool,
) -> dict[str, int]:
    before_alias = _count_provider(client, alias)
    before_canonical = _count_provider(client, canonical)

    if before_alias == 0:
        return {
            "before_alias": 0,
            "before_canonical": before_canonical,
            "updated": 0,
            "deleted": 0,
            "after_alias": 0,
            "after_canonical": before_canonical,
        }

    updated = 0
    deleted = 0
    if not dry_run:
        try:
            response = (
                client.table("exchange_rates")
                .update({"provider": canonical, "provider_type": canonical_type}, count="exact")
                .eq("provider", alias)
                .execute()
            )
            updated = response.count or 0
        except APIError as e:
            if not _is_unique_violation(e):
                raise
            updated, deleted = _rowwise_fallback(client, alias, canonical, dry_run=False)
    else:
        updated = before_alias

    after_alias = before_alias if dry_run else _count_provider(client, alias)
    after_canonical = before_canonical + updated if dry_run else _count_provider(client, canonical)
    return {
        "before_alias": before_alias,
        "before_canonical": before_canonical,
        "updated": updated,
        "deleted": deleted,
        "after_alias": after_alias,
        "after_canonical": after_canonical,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = get_client()
    alias = "United Currency"
    canonical = "UnitedCurrency"

    summary = normalize_provider_alias(
        client=client,
        alias=alias,
        canonical=canonical,
        canonical_type="Offline",
        dry_run=args.dry_run,
    )

    print(f"Alias provider: {alias}")
    print(f"Canonical provider: {canonical}")
    print(f"Rows before - alias: {summary['before_alias']}, canonical: {summary['before_canonical']}")
    if args.dry_run:
        print(f"Dry run - would update: {summary['updated']}")
    else:
        print(f"Updated rows: {summary['updated']}")
        if summary["deleted"]:
            print(f"Deleted duplicate rows: {summary['deleted']}")
    print(f"Rows after - alias: {summary['after_alias']}, canonical: {summary['after_canonical']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
