"""AusMoneySaver - Exchange Rate Scraper

Fetches and compares exchange rates from Australian banks and fintech
providers so users can find the best deal.
"""

import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from datetime import datetime

from scrapers.base import TARGET_CURRENCIES, ProviderResult
from scrapers import (
    scrape_anz,
    scrape_commbank,
    scrape_wise,
    scrape_remitly,
    scrape_united_exchange,
    scrape_travel_money_oz,
)


SCRAPERS: list[tuple[str, callable]] = [
    ("ANZ", scrape_anz),
    ("CommBank", scrape_commbank),
    ("Wise", scrape_wise),
    ("Remitly", scrape_remitly),
    ("UnitedCurrency", scrape_united_exchange),
    ("TravelMoneyOz", scrape_travel_money_oz),
]


def _fmt(value: float | None) -> str:
    if value is None:
        return "       N/A "
    if value >= 1000:
        return f"{value:>11.2f}"
    if value >= 100:
        return f"{value:>11.2f}"
    if value >= 10:
        return f"{value:>11.4f}"
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
            fees_shown = set()
            for code, rate in r.rates.items():
                if rate.fee is not None and rate.fee not in fees_shown:
                    fees_shown.add(rate.fee)
            if fees_shown:
                print(f"  {r.provider}: {', '.join(f'${f} AUD' for f in sorted(fees_shown))}")

    print("\nAll rates expressed as: 1 AUD = X foreign currency")
    print("Send -> : rate when sending AUD overseas (you buy foreign currency)")
    print("<- Recv : rate when receiving foreign currency (you sell to get AUD)")


def main(save_to_db: bool = False) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("AusMoneySaver - Exchange Rate Scraper")
    print(f"Time: {now}")
    print("-" * 40)

    results: list[ProviderResult] = []

    for name, scraper in SCRAPERS:
        try:
            print(f"  Fetching {name}...", end=" ", flush=True)
            data = scraper()
            results.append(data)
            count = len(data.rates)
            print(f"OK ({count} currencies)")
        except Exception as e:
            print(f"FAILED - {e}")

    if not results:
        print("\nNo data could be fetched from any provider.")
        return

    print_comparison(results)

    if save_to_db:
        try:
            from db import save_results
            count = save_results(results)
            print(f"\n[DB] Saved {count} rows to Supabase.")
        except Exception as e:
            print(f"\n[DB] Failed to save: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="Save results to Supabase DB")
    args = parser.parse_args()
    main(save_to_db=args.save)
