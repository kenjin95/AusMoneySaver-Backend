"""Validate required Supabase objects for the scraper pipeline."""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from postgrest.exceptions import APIError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db import get_client

REQUIRED_ENDPOINTS = (
    "exchange_rates",
    "latest_exchange_rates",
    "scrape_runs",
    "rate_alerts",
)


def decode_jwt_role(token: str) -> str:
    if token.count(".") < 2:
        return "unknown"
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8")
        return json.loads(decoded).get("role", "unknown")
    except Exception:
        return "unknown"


def is_service_role_like_key(token: str) -> bool:
    if token.startswith("sb_secret_"):
        return True
    return decode_jwt_role(token) == "service_role"


def main() -> int:
    load_dotenv()

    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY", "")
    key_role = decode_jwt_role(key)
    if not is_service_role_like_key(key):
        print(
            "[FAIL] SUPABASE_SERVICE_ROLE_KEY is not configured correctly. "
            f"Detected role={key_role!r}.",
            file=sys.stderr,
        )
        return 1

    client = get_client()
    failed = False
    for endpoint in REQUIRED_ENDPOINTS:
        try:
            client.table(endpoint).select("*").limit(1).execute()
            print(f"[OK] {endpoint}")
        except APIError as e:
            failed = True
            print(f"[FAIL] {endpoint}: {e}", file=sys.stderr)

    if failed:
        print(
            "\nRun `supabase_setup.sql` in Supabase SQL Editor and retry.",
            file=sys.stderr,
        )
        return 1

    print("Schema health check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
