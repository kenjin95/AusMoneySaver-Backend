"""AusMoneySaver - Exchange Rate Scraper.

Fetches and compares exchange rates from Australian banks and fintech
providers so users can find the best deal.
"""

import argparse
import io
import os
import sys
from datetime import datetime, timezone
from typing import Callable

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from scrapers.base import TARGET_CURRENCIES, ProviderResult
from scrapers import (
    scrape_anz,
    scrape_commbank,
    scrape_nab,
    scrape_westpac,
    scrape_wise,
    scrape_remitly,
    scrape_ofx,
    scrape_united_exchange,
    scrape_travel_money_oz,
    scrape_travelex,
)


SCRAPERS: list[tuple[str, Callable[[], ProviderResult]]] = [
    ("ANZ", scrape_anz),
    ("CommBank", scrape_commbank),
    ("NAB", scrape_nab),
    ("Westpac", scrape_westpac),
    ("Wise", scrape_wise),
    ("Remitly", scrape_remitly),
    ("OFX", scrape_ofx),
    ("UnitedCurrency", scrape_united_exchange),
    ("TravelMoneyOz", scrape_travel_money_oz),
    ("Travelex", scrape_travelex),
]

DEFAULT_MIN_SUCCESS_PROVIDERS = int(os.getenv("MIN_SUCCESS_PROVIDERS", "5"))


def _fmt(value: float | None) -> str:
    if value is None:
        return "       N/A "
    if value >= 100:
        return f"{value:>11.2f}"
    return f"{value:>11.4f}"


def print_comparison(results: list[ProviderResult]) -> None:
    providers = [r.provider for r in results]
    col_w = 24

    print()
    line_w = 10 + col_w * len(providers)
    print("=" * line_w)

    name_row = f"{'':10}"
    for p in providers:
        name_row += f"{p:^{col_w}}"
    print(name_row)

    sub_row = f"{'':10}"
    for _ in providers:
        sub_row += f"{'Send ->':>{col_w // 2}}{'<- Recv':>{col_w // 2}}"
    print(sub_row)
    print("-" * line_w)

    for code in TARGET_CURRENCIES:
        row = f"{code:<10}"
        for r in results:
            rate = r.rates.get(code)
            if rate:
                s = _fmt(rate.send_rate)
                rv = _fmt(rate.receive_rate)
                row += f"{s} {rv}"
            else:
                row += f"{'-- N/A --':^{col_w}}"
        print(row)

    print("=" * line_w)

    has_fee = any(
        rate.fee is not None
        for r in results
        for rate in r.rates.values()
    )
    if has_fee:
        print("\n* Fintech fees (per transfer):")
        for r in results:
            fees_shown = sorted(
                {rate.fee for rate in r.rates.values() if rate.fee is not None}
            )
            if fees_shown:
                print(f"  {r.provider}: {', '.join(f'${f} AUD' for f in fees_shown)}")

    print("\nAll rates expressed as: 1 AUD = X foreign currency")
    print("Send -> : rate when sending AUD overseas (you buy foreign currency)")
    print("<- Recv : rate when receiving foreign currency (you sell to get AUD)")


def _persist_run_summary(
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
    results: list[ProviderResult],
    failures: list[dict[str, str]],
    rows_inserted: int,
    status: str,
) -> bool:
    try:
        from db import save_run_summary
        save_run_summary(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            results=results,
            failures=failures,
            rows_inserted=rows_inserted,
            status=status,
        )
        print("[DB] Run summary saved.")
        return True
    except Exception as e:
        print(f"[DB] Run summary save failed: {e}")
        return False


def main(
    save_to_db: bool = False,
    min_success_providers: int = DEFAULT_MIN_SUCCESS_PROVIDERS,
    allow_partial_success: bool = False,
) -> int:
    if min_success_providers < 1 or min_success_providers > len(SCRAPERS):
        raise ValueError(f"--min-success-providers must be between 1 and {len(SCRAPERS)}")

    started_at = datetime.now(timezone.utc)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_id = os.getenv("SCRAPE_RUN_ID", started_at.strftime("manual-%Y%m%dT%H%M%SZ"))

    print("AusMoneySaver - Exchange Rate Scraper")
    print(f"Time: {now}")
    print(f"Run ID: {run_id}")
    print("-" * 40)

    results: list[ProviderResult] = []
    failures: list[dict[str, str]] = []

    for name, scraper in SCRAPERS:
        try:
            print(f"  Fetching {name}...", end=" ", flush=True)
            data = scraper()
            count = len(data.rates)
            if count == 0:
                raise RuntimeError("no rates returned")
            results.append(data)
            print(f"OK ({count} currencies)")
        except Exception as e:
            error_text = str(e)
            failures.append({"provider": name, "error": error_text})
            print(f"FAILED - {error_text}")

    if not results:
        print("\nNo data could be fetched from any provider.")
        if save_to_db:
            _persist_run_summary(
                run_id=run_id,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                results=[],
                failures=failures,
                rows_inserted=0,
                status="failed",
            )
        return 1

    print_comparison(results)

    should_fail = False
    if len(results) < min_success_providers:
        should_fail = True
        print(
            f"\n[QUALITY] Failed: {len(results)}/{len(SCRAPERS)} providers succeeded "
            f"(required >= {min_success_providers})."
        )

    if failures and not allow_partial_success:
        should_fail = True
        print(
            "\n[QUALITY] Failed: one or more providers failed. "
            "Use --allow-partial-success to permit partial runs."
        )

    rows_saved = 0
    if save_to_db:
        if should_fail:
            print("\n[DB] Skipping save because run did not meet success criteria.")
        else:
            try:
                from db import save_results
                rows_saved = save_results(results, run_id=run_id)
                print(f"\n[DB] Saved {rows_saved} rows to Supabase.")
            except Exception as e:
                print(f"\n[DB] Failed to save: {e}")
                should_fail = True

        status = "failed" if should_fail else ("partial" if failures else "success")
        summary_ok = _persist_run_summary(
            run_id=run_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            results=results,
            failures=failures,
            rows_inserted=rows_saved,
            status=status,
        )
        if not summary_ok:
            print("[DB] Continuing despite run summary save failure.")

    if failures:
        print("\nFailed providers:")
        for failure in failures:
            print(f"  - {failure['provider']}: {failure['error']}")

    return 1 if should_fail else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="Save results to Supabase DB")
    parser.add_argument(
        "--min-success-providers",
        type=int,
        default=DEFAULT_MIN_SUCCESS_PROVIDERS,
        help=f"Minimum successful providers required (1-{len(SCRAPERS)}).",
    )
    parser.add_argument(
        "--allow-partial-success",
        action="store_true",
        help="Allow runs with failed providers if minimum success threshold is met.",
    )
    args = parser.parse_args()
    raise SystemExit(
        main(
            save_to_db=args.save,
            min_success_providers=args.min_success_providers,
            allow_partial_success=args.allow_partial_success,
        )
    )
