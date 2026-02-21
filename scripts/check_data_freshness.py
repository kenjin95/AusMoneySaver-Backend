"""Fail if exchange rate data is stale."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

ENDPOINTS = (
    "latest_exchange_rates?select=scraped_at&order=scraped_at.desc&limit=1",
    "exchange_rates?select=scraped_at&order=scraped_at.desc&limit=1",
)


def parse_timestamp(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def resolve_supabase_key() -> str:
    return (
        os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or ""
    )


def fetch_latest_scraped_at(supabase_url: str, supabase_key: str) -> tuple[datetime, str]:
    headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}", "Accept": "application/json"}

    errors: list[str] = []
    for endpoint in ENDPOINTS:
        url = f"{supabase_url.rstrip('/')}/rest/v1/{endpoint}"
        try:
            response = requests.get(url, headers=headers, timeout=20)
        except requests.RequestException as e:
            errors.append(f"{endpoint}: {e}")
            continue

        if not response.ok:
            errors.append(f"{endpoint}: HTTP {response.status_code}")
            continue

        payload = response.json()
        if not payload:
            errors.append(f"{endpoint}: empty payload")
            continue

        return parse_timestamp(payload[0]["scraped_at"]), endpoint

    raise RuntimeError(" / ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold-minutes", type=int, default=120)
    args = parser.parse_args()

    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = resolve_supabase_key()
    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "SUPABASE_URL and one of SUPABASE_ANON_KEY/SUPABASE_KEY/"
            "SUPABASE_SERVICE_ROLE_KEY are required."
        )

    latest_dt, source_endpoint = fetch_latest_scraped_at(supabase_url, supabase_key)
    now = datetime.now(timezone.utc)
    age_minutes = (now - latest_dt).total_seconds() / 60

    print(f"Source endpoint: {source_endpoint}")
    print(f"Latest scraped_at (UTC): {latest_dt.isoformat()}")
    print(f"Now (UTC): {now.isoformat()}")
    print(f"Data age (minutes): {age_minutes:.1f}")
    print(f"Threshold (minutes): {args.threshold_minutes}")

    if age_minutes > args.threshold_minutes:
        print("Freshness check failed: data is stale.")
        return 1

    print("Freshness check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
