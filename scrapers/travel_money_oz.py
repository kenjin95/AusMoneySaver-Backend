import uuid

import requests

from scrapers.base import CurrencyRate, ProviderResult

API_URL = "https://eeermgmu4a.execute-api.ap-southeast-2.amazonaws.com/Prod/rates/cash/all/v1"


def scrape_travel_money_oz() -> ProviderResult:
    """Fetch Travel Money Oz cash exchange rates via their public API.

    POST with a random correlation/request ID.
    Returns buy rates only (AUD -> foreign cash).
    90+ physical stores across Australia.
    """
    result = ProviderResult(provider="TravelMoneyOz", provider_type="Offline")

    payload = {
        "CorrelationId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
        "SourceCurrency": "AUD",
        "IsQuote": False,
    }

    try:
        resp = requests.post(
            API_URL,
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.travelmoneyoz.com",
                "Referer": "https://www.travelmoneyoz.com/",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise RuntimeError(f"request failed: {e}") from e
    except ValueError as e:
        raise RuntimeError(f"invalid json response: {e}") from e

    if not data.get("IsSuccess"):
        raise RuntimeError("API returned IsSuccess=false")

    for entry in data.get("Data", {}).get("Rates", []):
        code = entry.get("TargetCurrency", "").upper()
        rate = entry.get("ExchangeRate")
        if not code or rate is None:
            continue
        try:
            rate_value = float(rate)
        except (TypeError, ValueError):
            continue
        if rate_value <= 0:
            continue
        result.rates[code] = CurrencyRate(
            currency_code=code,
            send_rate=rate_value,
        )

    if not result.rates:
        raise RuntimeError("API returned no usable rates")

    return result
