import requests

from scrapers.base import CurrencyRate, ProviderResult

API_URL = "https://api.travelex.net/salt/rates/current"
QUERY = {
    "key": "Travelex",
    "site": "/AU",
}
HEADERS = {
    "Accept": "application/json",
    "Origin": "https://www.travelex.com.au",
    "Referer": "https://www.travelex.com.au/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


def _to_float(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
        return num if num > 0 else None
    except (TypeError, ValueError):
        return None


def scrape_travelex() -> ProviderResult:
    """Fetch Travelex Australia cash exchange rates from their public API.

    Returned values are interpreted as AUD -> foreign cash rates (send_rate).
    """
    response = requests.get(API_URL, params=QUERY, headers=HEADERS, timeout=20)
    response.raise_for_status()
    payload = response.json()

    result = ProviderResult(provider="Travelex", provider_type="Offline")
    timestamp = payload.get("lastModified")
    if isinstance(timestamp, str) and timestamp:
        result.timestamp = timestamp

    rates = payload.get("rates", {})
    if not isinstance(rates, dict):
        raise RuntimeError("Travelex API returned invalid rates payload")

    for code, value in rates.items():
        currency = str(code).upper()
        if len(currency) != 3 or not currency.isalpha():
            continue
        send_rate = _to_float(value)
        if send_rate is None:
            continue
        result.rates[currency] = CurrencyRate(
            currency_code=currency,
            send_rate=send_rate,
        )

    if not result.rates:
        raise RuntimeError("Travelex API returned no usable rates")

    return result
