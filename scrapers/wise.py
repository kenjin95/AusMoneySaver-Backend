import re

import requests
from bs4 import BeautifulSoup

from scrapers.base import CurrencyRate, ProviderResult, TARGET_CURRENCIES

COMPARE_URL = "https://wise.com/au/compare/best-{code}-exchange-rates"
CONVERTER_URL = "https://wise.com/au/currency-converter/aud-to-{code}-rate"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


def _extract_aud_rate(text: str, code: str) -> float | None:
    rate_pattern = rf"1\s*AUD\s*=\s*([\d,]+\.?\d*)\s*{code}"
    match = re.search(rate_pattern, text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _scrape_compare_page(code: str) -> CurrencyRate | None:
    """Scrape the Wise compare page for a specific currency.

    Returns mid-market rate and Wise fee for 1000 AUD transfer.
    """
    url = COMPARE_URL.format(code=code.lower())
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    mid_rate = _extract_aud_rate(text, code)

    fee = None
    fee_match = re.search(r"([\d.]+)\s*AUD\s*Transparent\s*fee", text, re.IGNORECASE)
    if fee_match:
        fee = float(fee_match.group(1))

    if mid_rate is None:
        return None

    return CurrencyRate(
        currency_code=code,
        send_rate=mid_rate,
        receive_rate=mid_rate,
        fee=fee,
    )


def _scrape_converter_page(code: str) -> CurrencyRate | None:
    """Fallback: scrape the simpler currency converter page."""
    url = CONVERTER_URL.format(code=code.lower())
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    mid_rate = _extract_aud_rate(text, code)
    if mid_rate is None:
        return None
    return CurrencyRate(
        currency_code=code,
        send_rate=mid_rate,
        receive_rate=mid_rate,
    )


def scrape_wise() -> ProviderResult:
    """Scrape Wise mid-market exchange rates.

    Wise uses the mid-market rate (no markup) and charges a separate
    transparent fee. The fee shown is for a 1000 AUD transfer.
    """
    result = ProviderResult(provider="Wise", provider_type="Fintech")

    for code in TARGET_CURRENCIES:
        rate = _scrape_compare_page(code)
        if rate is None:
            rate = _scrape_converter_page(code)
        if rate is not None:
            result.rates[code] = rate

    return result
