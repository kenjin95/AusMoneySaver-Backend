import requests

from scrapers.base import CurrencyRate, ProviderResult, TARGET_CURRENCIES

API_BASE = "https://api.ofx.com/PublicSite.ApiService/"
HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-AU,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}
QUOTE_AMOUNT_AUD = 1000


def _to_float(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
        return num if num > 0 else None
    except (TypeError, ValueError):
        return None


def _fetch_rate(session: requests.Session, code: str) -> tuple[float | None, float | None]:
    url = f"{API_BASE}OFX/spotrate/Individual/AUD/{code}/{QUOTE_AMOUNT_AUD}"
    response = session.get(url, headers=HEADERS, timeout=20)
    if response.status_code in {400, 403, 404}:
        return None, None
    response.raise_for_status()
    payload = response.json()
    return _to_float(payload.get("CustomerRate")), _to_float(payload.get("Fee"))


def scrape_ofx() -> ProviderResult:
    """Fetch OFX customer rates from their public calculator API.

    OFX exposes a customer transfer rate for AUD -> foreign. The API does
    not expose a separate reverse-side retail rate for the same quote path,
    so receive_rate is set equal to send_rate.
    """
    result = ProviderResult(provider="OFX", provider_type="Fintech")

    with requests.Session() as session:
        for code in TARGET_CURRENCIES:
            send_rate, fee = _fetch_rate(session, code)
            if send_rate is None:
                continue
            result.rates[code] = CurrencyRate(
                currency_code=code,
                send_rate=send_rate,
                receive_rate=send_rate,
                fee=fee,
            )

    if not result.rates:
        raise RuntimeError("OFX returned no usable rates")

    return result
