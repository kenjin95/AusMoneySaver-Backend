"""Fail if exchange rate data is stale."""

from __future__ import annotations

import argparse
import os
import time
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
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
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

        raw_ts = payload[0].get("scraped_at")
        if not raw_ts:
            errors.append(f"{endpoint}: scraped_at missing")
            continue

        try:
            return parse_timestamp(raw_ts), endpoint
        except (TypeError, ValueError):
            errors.append(f"{endpoint}: invalid scraped_at={raw_ts!r}")
            continue

    raise RuntimeError(" / ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold-minutes", type=int, default=120)
    parser.add_argument(
        "--retry-attempts",
        type=int,
        default=0,
        help="How many additional checks to run after a stale/failure result.",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=int,
        default=120,
        help="Delay between retry attempts.",
    )
    args = parser.parse_args()
    if args.retry_attempts < 0:
        raise ValueError("--retry-attempts must be >= 0")
    if args.retry_delay_seconds < 1:
        raise ValueError("--retry-delay-seconds must be >= 1")

    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = resolve_supabase_key()
    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "SUPABASE_URL and one of SUPABASE_ANON_KEY/SUPABASE_KEY/"
            "SUPABASE_SERVICE_ROLE_KEY are required."
        )

    total_attempts = args.retry_attempts + 1
    for attempt in range(1, total_attempts + 1):
        if total_attempts > 1:
            print(f"Attempt {attempt}/{total_attempts}")
        try:
            latest_dt, source_endpoint = fetch_latest_scraped_at(supabase_url, supabase_key)
            now = datetime.now(timezone.utc)
            age_minutes = (now - latest_dt).total_seconds() / 60

            print(f"Source endpoint: {source_endpoint}")
            print(f"Latest scraped_at (UTC): {latest_dt.isoformat()}")
            print(f"Now (UTC): {now.isoformat()}")
            print(f"Data age (minutes): {age_minutes:.1f}")
            print(f"Threshold (minutes): {args.threshold_minutes}")

            if age_minutes <= args.threshold_minutes:
                print("Freshness check passed.")
                return 0

            last_error = "Freshness check failed: data is stale."
        except Exception as e:
            last_error = f"Freshness check failed: {e}"

        if attempt < total_attempts:
            print(f"{last_error} Retrying in {args.retry_delay_seconds} seconds...")
            time.sleep(args.retry_delay_seconds)
            continue

        print(last_error)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
