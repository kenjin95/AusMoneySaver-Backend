import re

import requests
from bs4 import BeautifulSoup

from scrapers.base import CurrencyRate, ProviderResult, TARGET_CURRENCIES

CONVERTER_URL = "https://www.remitly.com/au/en/currency-converter/aud-to-{code}-rate"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

CURRENCY_TO_COUNTRY = {
    "KRW": "south-korea",
    "CNY": "china",
    "INR": "india",
    "USD": "united-states",
    "GBP": "united-kingdom",
    "JPY": "japan",
    "NZD": "new-zealand",
    "PHP": "philippines",
    "VND": "vietnam",
    "IDR": "indonesia",
    "THB": "thailand",
    "MYR": "malaysia",
    "NPR": "nepal",
    "ZAR": "south-africa",
    "CAD": "canada",
    "LKR": "sri-lanka",
    "CLP": "chile",
}

PRICING_URL = "https://www.remitly.com/au/en/{country}/pricing"


def _scrape_converter(code: str) -> CurrencyRate | None:
    """Scrape Remitly's currency converter page for a rate.

    Looks for patterns like "1013.13 KRW to 1 AUD" or "1 AUD = 1013.13 KRW".
    """
    url = CONVERTER_URL.format(code=code.lower())
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
    except requests.RequestException:
        return None

    text = resp.text

    patterns = [
        rf"([\d,]+\.?\d*)\s*{code}\s*to\s*1\s*AUD",
        rf"1\s*AUD[^<]{{0,30}}([\d,]+\.?\d*)\s*{code}",
        rf"rate\s*of\s*([\d,]+\.?\d*)\s*{code}",
    ]

    rate_val = None
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                rate_val = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                continue

    if rate_val is None or rate_val <= 0:
        return None

    fee = None
    fee_patterns = [
        r"ECONOMY[^$]*\$([\d.]+)",
        r"\$([\d.]+)\s*\|\s*\$([\d.]+)",
    ]

    soup = BeautifulSoup(text, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    for pat in fee_patterns:
        m = re.search(pat, page_text)
        if m:
            try:
                fee = float(m.group(1))
                break
            except ValueError:
                continue

    return CurrencyRate(
        currency_code=code,
        send_rate=rate_val,
        receive_rate=rate_val,
        fee=fee,
    )


def _scrape_pricing(code: str) -> CurrencyRate | None:
    """Fallback: scrape the pricing/country page."""
    country = CURRENCY_TO_COUNTRY.get(code)
    if not country:
        return None

    url = PRICING_URL.format(country=country)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
    except requests.RequestException:
        return None

    text = resp.text

    patterns = [
        rf"([\d,]+\.?\d*)\s*{code}\s*to\s*1\s*AUD",
        rf"rate\s*of\s*([\d,]+\.?\d*)\s*{code}",
        rf"1\s*AUD[^<]{{0,30}}([\d,]+\.?\d*)\s*{code}",
    ]

    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                rate_val = float(m.group(1).replace(",", ""))
                if rate_val > 0:
                    return CurrencyRate(
                        currency_code=code,
                        send_rate=rate_val,
                        receive_rate=rate_val,
                    )
            except ValueError:
                continue

    return None


def scrape_remitly() -> ProviderResult:
    """Scrape Remitly exchange rates from their public pages.

    Remitly shows promotional rates for new customers; the rate we capture
    is their advertised rate (may include new-customer bonus on first $1000).
    Fees: Economy $1.99, Express $3.99 per transfer.
    """
    result = ProviderResult(provider="Remitly", provider_type="fintech")

    for code in TARGET_CURRENCIES:
        rate = _scrape_converter(code)
        if rate is None:
            rate = _scrape_pricing(code)
        if rate is not None:
            result.rates[code] = rate

    return result
