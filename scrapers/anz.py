import requests
from bs4 import BeautifulSoup

from scrapers.base import CurrencyRate, ProviderResult

URL = "https://www.anz.com/aus/ratefee/fxrates/fxpopup.asp"


def _parse_rate(value: str) -> float | None:
    cleaned = value.strip().replace(",", "")
    if cleaned in ("N/A", "O/A", ""):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def scrape_anz() -> ProviderResult:
    """Scrape ANZ foreign exchange rates from their public HTML table.

    Rates are expressed as 1 AUD = X foreign currency.
    - Bank Buys IMT/TT = rate when customer converts foreign → AUD (receive)
    - Bank Sells IMT/TT = rate when customer converts AUD → foreign (send)
    """
    resp = requests.get(URL, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    result = ProviderResult(provider="ANZ", provider_type="Bank")

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 9:
            continue

        code = cells[2].get_text(strip=True).upper()
        if not code or len(code) != 3 or not code.isalpha():
            continue

        buy_imt = _parse_rate(cells[3].get_text(strip=True))
        sell_imt = _parse_rate(cells[6].get_text(strip=True))

        result.rates[code] = CurrencyRate(
            currency_code=code,
            receive_rate=buy_imt,
            send_rate=sell_imt,
        )

    return result
