"""Validate public API exposure stays limited to intended endpoints."""

from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv


def request(endpoint: str, key: str) -> requests.Response:
    url = f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{endpoint}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    return requests.get(url, headers=headers, timeout=20)


def main() -> int:
    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not supabase_url or not anon_key:
        print(
            "[FAIL] SUPABASE_URL and SUPABASE_ANON_KEY are required.",
            file=sys.stderr,
        )
        return 1

    os.environ["SUPABASE_URL"] = supabase_url

    checks = [
        (
            "latest_exchange_rates?select=provider,currency,send_rate,scraped_at&limit=1",
            {200},
            "[OK] latest_exchange_rates is publicly readable.",
        ),
        (
            "exchange_rates?select=id,provider,currency,send_rate&limit=1",
            {401, 403},
            "[OK] exchange_rates raw history is not publicly readable.",
        ),
        (
            "rate_alerts?select=*&limit=1",
            {401, 403},
            "[OK] rate_alerts is not publicly readable.",
        ),
        (
            "scrape_runs?select=*&limit=1",
            {401, 403},
            "[OK] scrape_runs is not publicly readable.",
        ),
    ]

    failed = False
    for endpoint, allowed_statuses, ok_message in checks:
        response = request(endpoint, anon_key)
        if response.status_code in allowed_statuses:
            print(ok_message)
            continue
        failed = True
        print(
            f"[FAIL] {endpoint} returned HTTP {response.status_code}: {response.text[:300]}",
            file=sys.stderr,
        )

    if failed:
        return 1

    print("Public API exposure check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
