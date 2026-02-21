import html
import json
import re

import requests

from scrapers.base import CurrencyRate, ProviderResult

PAGE_URL = "https://www.nab.com.au/personal/international-banking/foreign-exchange-rates"
DEFAULT_API_HOST = "https://customer.api.nab.com.au"
TOKEN_PATH = "/v1/idp/oauth/token"
BFF_PATH = "/v1/content/nab-calculators-fx-bff"

DEFAULT_ANON_CLIENT_ID = "69CC21FB-CDCA-027F-1BCF-475DF53D3C23"
DEFAULT_ANON_GRANT_TYPE = "nab:anonymous"
DEFAULT_ANON_SCOPE = (
    "custoffer:edbcc:readsubmission custoffer:referencedata:read "
    "forms:form:get forms:submission forms:submission:create frauddetect:self-service"
)

DEFAULT_EXCHANGE_CLIENT_ID = "69406D32-05CB-F258-064F-E7D6CA23F48E"
DEFAULT_EXCHANGE_SCOPE = "content:fxcalculator:convert forms:form:get"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://www.nab.com.au",
    "Referer": "https://www.nab.com.au/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

RATES_QUERY = (
    "query getRates($input: String) {\n"
    "  getRates(input: $input) {\n"
    "    timestamp\n"
    "    rates {\n"
    "      currencyCode\n"
    "      direction\n"
    "      buyRate\n"
    "      sellRate\n"
    "      __typename\n"
    "    }\n"
    "    __typename\n"
    "  }\n"
    "}"
)


def _to_float(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
        return num if num > 0 else None
    except (TypeError, ValueError):
        return None


def _load_shell_config(session: requests.Session) -> dict:
    response = session.get(PAGE_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    match = re.search(r'<mini-app-loader[^>]+config="([^"]+)"', response.text)
    if not match:
        return {}

    config_raw = html.unescape(match.group(1))
    try:
        config = json.loads(config_raw)
    except json.JSONDecodeError:
        return {}

    shell_raw = config.get("shellConfig", "{}")
    if isinstance(shell_raw, dict):
        return shell_raw
    try:
        return json.loads(shell_raw)
    except (TypeError, ValueError):
        return {}


def _request_anonymous_token(
    session: requests.Session,
    api_host: str,
    shell_config: dict,
) -> tuple[str, str]:
    client_id = str(shell_config.get("kongClientId") or DEFAULT_ANON_CLIENT_ID)
    grant_type = str(shell_config.get("grantType") or DEFAULT_ANON_GRANT_TYPE)
    scope = str(shell_config.get("scope") or DEFAULT_ANON_SCOPE)

    payload = {
        "client_id": client_id,
        "grant_type": grant_type,
        "scope": scope,
    }
    response = session.post(
        f"{api_host}{TOKEN_PATH}",
        headers=HEADERS,
        json=payload,
        timeout=25,
    )
    if not response.ok:
        raise RuntimeError(f"anonymous token request failed (HTTP {response.status_code})")

    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("anonymous token missing in response")
    return token, client_id


def _request_exchange_token(
    session: requests.Session,
    api_host: str,
    actor_token: str,
    anon_client_id: str,
) -> str:
    candidate_client_ids = [DEFAULT_EXCHANGE_CLIENT_ID, anon_client_id]

    for client_id in candidate_client_ids:
        payload = {
            "client_id": client_id,
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "subject_token": client_id,
            "subject_token_type": "nab:oauth:token-type:client_id",
            "actor_token": actor_token,
            "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "scope": DEFAULT_EXCHANGE_SCOPE,
        }
        response = session.post(
            f"{api_host}{TOKEN_PATH}",
            headers=HEADERS,
            json=payload,
            timeout=25,
        )
        if not response.ok:
            continue
        token = response.json().get("access_token")
        if token:
            return token

    raise RuntimeError("token-exchange request failed")


def scrape_nab() -> ProviderResult:
    """Fetch NAB IMT rates via the public mini-app API flow.

    For this endpoint, buyRate is treated as send_rate (AUD -> foreign),
    and sellRate as receive_rate (foreign -> AUD), matching the observed
    value ordering (buyRate < sellRate).
    """
    result = ProviderResult(provider="NAB", provider_type="Bank")

    with requests.Session() as session:
        shell_config = _load_shell_config(session)
        api_host = str(shell_config.get("kongEsgEndPoint") or DEFAULT_API_HOST).rstrip("/")

        anon_token, anon_client_id = _request_anonymous_token(session, api_host, shell_config)
        exchange_token = _request_exchange_token(session, api_host, anon_token, anon_client_id)

        query_payload = {
            "operationName": "getRates",
            "variables": {"input": "IMT"},
            "query": RATES_QUERY,
        }
        headers = dict(HEADERS)
        headers["Accept"] = "*/*"
        headers["Authorization"] = f"Bearer {exchange_token}"

        response = session.post(
            f"{api_host}{BFF_PATH}",
            headers=headers,
            json=query_payload,
            timeout=25,
        )
        if not response.ok:
            raise RuntimeError(f"NAB rates query failed (HTTP {response.status_code})")
        payload = response.json().get("data", {}).get("getRates", {})

    timestamp = payload.get("timestamp")
    if isinstance(timestamp, str) and timestamp:
        result.timestamp = timestamp

    rows = payload.get("rates", [])
    for row in rows:
        code = str(row.get("currencyCode", "")).upper()
        if len(code) != 3 or not code.isalpha():
            continue

        send_rate = _to_float(row.get("buyRate"))
        receive_rate = _to_float(row.get("sellRate"))
        if send_rate is None and receive_rate is None:
            continue

        result.rates[code] = CurrencyRate(
            currency_code=code,
            send_rate=send_rate,
            receive_rate=receive_rate,
        )

    if not result.rates:
        raise RuntimeError("NAB returned no usable rates")

    return result
