import re

from playwright.sync_api import Page, sync_playwright

from scrapers.base import CurrencyRate, ProviderResult

URL = "https://www.westpac.com.au/personal-banking/services/currency-converter/"
MAX_ATTEMPTS = 2

CODE_PATTERN = re.compile(r"\(([A-Z]{3})\)$")


def _parse_rate(body_text: str, code: str) -> float | None:
    pattern = rf"1\s*AUD\s*=\s*([\d,]+(?:\.\d+)?)\s*{code}\s*exchange\s*rate"
    match = re.search(pattern, body_text, re.IGNORECASE)
    if not match:
        return None
    try:
        rate_value = float(match.group(1).replace(",", ""))
        return rate_value if rate_value > 0 else None
    except ValueError:
        return None


def _list_currency_options(page: Page) -> list[tuple[str, str]]:
    page.wait_for_selector("#receivingCurrencyButton", state="attached", timeout=30_000)
    try:
        page.locator("#receivingCurrencyButton").first.click(timeout=10_000, force=True)
    except Exception:
        page.evaluate("document.querySelector('#receivingCurrencyButton')?.click()")
    page.wait_for_timeout(400)

    options = []
    seen: set[str] = set()
    nodes = page.locator("button[role='option']")
    for i in range(nodes.count()):
        label = nodes.nth(i).inner_text().strip()
        match = CODE_PATTERN.search(label)
        if not match:
            continue
        code = match.group(1)
        if code == "AUD" or code in seen:
            continue
        seen.add(code)
        options.append((code, label))

    page.keyboard.press("Escape")
    return options


def _select_currency(page: Page, label: str) -> None:
    page.wait_for_selector("#receivingCurrencyButton", state="attached", timeout=30_000)
    try:
        page.locator("#receivingCurrencyButton").first.click(timeout=10_000, force=True)
    except Exception:
        page.evaluate("document.querySelector('#receivingCurrencyButton')?.click()")
    page.wait_for_timeout(200)
    page.locator("button[role='option']", has_text=label).first.click(timeout=5_000)
    page.wait_for_timeout(1_000)


def _wait_for_calculator(page: Page) -> None:
    page.wait_for_selector("#receivingCurrencyButton", state="visible", timeout=90_000)
    page.wait_for_selector("#productType", state="attached", timeout=30_000)
    page.wait_for_selector("#channelType", state="attached", timeout=30_000)


def scrape_westpac() -> ProviderResult:
    """Scrape Westpac send rates from the public currency converter UI.

    The page publishes "Send money overseas" rates as:
      1 AUD = X foreign currency
    These are captured as send_rate. Westpac's receive-side rates are not
    consistently exposed for all destination currencies, so receive_rate is
    left null.
    """
    result = ProviderResult(provider="Westpac", provider_type="Bank")

    last_error: Exception | None = None
    for _attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
                _wait_for_calculator(page)
                page.wait_for_timeout(2_000)

                currency_options = _list_currency_options(page)
                for code, label in currency_options:
                    try:
                        _select_currency(page, label)
                        body_text = page.inner_text("body")
                        rate = _parse_rate(body_text, code)
                        if rate is None:
                            continue
                        result.rates[code] = CurrencyRate(
                            currency_code=code,
                            send_rate=rate,
                        )
                    except Exception:
                        continue

                browser.close()

            if result.rates:
                return result
        except Exception as e:  # noqa: BLE001 - caller handles and records failures
            last_error = e

    if last_error is not None:
        raise RuntimeError(f"failed after {MAX_ATTEMPTS} attempts: {last_error}") from last_error
    raise RuntimeError("failed after retries: no rates scraped from Westpac")
