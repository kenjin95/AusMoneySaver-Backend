import re

from playwright.sync_api import sync_playwright

from scrapers.base import CurrencyRate, ProviderResult

URL = "https://www.unitedcurrencyexchange.com.au/"


def _extract_rates(body_text: str) -> tuple[dict[str, float], dict[str, float]]:
    """Parse the page body text to extract sell and buy rates.

    Sell section (FOREIGN CURRENCIES TO AUD):
      "KRW  10,000  $9.79"  => receive_rate = 10000 / 9.79
    Buy section (AUD TO FOREIGN CURRENCIES, identified by rate numbers after code):
      "KRW  965.3728  Collect in Store..."  => send_rate = 965.3728
    """
    lines = body_text.split("\n")
    sell_rates: dict[str, float] = {}
    buy_rates: dict[str, float] = {}

    in_sell = False
    in_buy = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if "FOREIGN CURRENCIES TO AUD" in stripped.upper():
            in_sell = True
            in_buy = False
            continue

        if re.search(r"AUD.{0,20}(100|50|20|10|5|2|1)", stripped) and "1.0000" in stripped:
            in_sell = False
            in_buy = True
            continue

        if in_sell:
            m = re.match(
                r"([A-Z]{3})\s+([\d,]+(?:\.\d+)?)\s+\$([\d,]+(?:\.\d+)?)",
                stripped,
            )
            if m:
                code = m.group(1)
                denomination = float(m.group(2).replace(",", ""))
                aud_amount = float(m.group(3).replace(",", ""))
                if aud_amount > 0:
                    sell_rates[code] = denomination / aud_amount

        if in_buy:
            m = re.match(
                r"([A-Z]{3})(?:\s+[^0-9]*)?\s+([\d,]+(?:\.\d+)?)\s+(?:Collect|Not Available|Available)",
                stripped,
            )
            if m:
                code = m.group(1)
                rate_val = float(m.group(2).replace(",", ""))
                if rate_val > 0:
                    buy_rates[code] = rate_val

    return sell_rates, buy_rates


def scrape_united_exchange() -> ProviderResult:
    """Scrape United Currency Exchange (Melbourne/Sydney offline cash exchange).

    This is a physical currency exchange with no online transfer service.
    All rates are for cash transactions (walk in with AUD, walk out with foreign).
    Rates expressed as 1 AUD = X foreign currency.
    """
    result = ProviderResult(provider="United Currency", provider_type="offline")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(5000)
        body_text = page.inner_text("body")
        browser.close()

    sell_rates, buy_rates = _extract_rates(body_text)

    all_codes = set(sell_rates.keys()) | set(buy_rates.keys())
    for code in all_codes:
        result.rates[code] = CurrencyRate(
            currency_code=code,
            send_rate=buy_rates.get(code),
            receive_rate=sell_rates.get(code),
        )

    return result
