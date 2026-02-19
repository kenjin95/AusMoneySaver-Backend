import time

import requests

from scrapers.base import CurrencyRate, ProviderResult

API_URL = "https://www.commbank.com.au/content/data/forex-rates/AUD.json"


def _to_float(value: str) -> float | None:
    try:
        v = float(value)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def scrape_commbank() -> ProviderResult:
    """Fetch CommBank exchange rates from their internal JSON API.

    JSON fields per currency:
      bbImt  = Bank Buys IMT  → receive_rate (foreign → AUD)
      bsImt  = Bank Sells IMT → send_rate   (AUD → foreign)
    All rates expressed as 1 AUD = X foreign currency.
    """
    cache_bust = int(time.time() * 1000)
    resp = requests.get(
        API_URL,
        params={"path": cache_bust},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    result = ProviderResult(provider="CommBank", provider_type="bank")
    result.timestamp = data.get("timeStamp", result.timestamp)

    for entry in data.get("currencies", []):
        code = entry.get("currencyTitle", "").upper()
        if not code or len(code) != 3:
            continue

        result.rates[code] = CurrencyRate(
            currency_code=code,
            send_rate=_to_float(entry.get("bsImt")),
            receive_rate=_to_float(entry.get("bbImt")),
        )

    return result
