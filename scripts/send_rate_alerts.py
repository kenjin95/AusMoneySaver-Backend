"""Send email notifications for triggered exchange-rate alerts."""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

import requests
from dotenv import load_dotenv

PROVIDER_FALLBACK_LINKS = {
    "ANZ": "https://www.anz.com.au/personal/travel-and-international/foreign-exchange",
    "CommBank": "https://www.commbank.com.au/international/foreign-exchange",
    "NAB": "https://www.nab.com.au/personal/international-banking/foreign-exchange-rates",
    "Westpac": "https://www.westpac.com.au/personal-banking/services/currency-converter/",
    "Wise": "https://wise.com/au",
    "Remitly": "https://www.remitly.com/au/en",
    "OFX": "https://www.ofx.com/en-au/currency-converter/",
    "UnitedCurrency": "https://www.unitedcurrencyexchange.com.au",
    "TravelMoneyOz": "https://www.travelmoneyoz.com.au",
    "Travelex": "https://www.travelex.com.au/",
}

PROVIDER_AFFILIATE_ENV = {
    "ANZ": "AFFILIATE_LINK_ANZ",
    "CommBank": "AFFILIATE_LINK_COMMBANK",
    "NAB": "AFFILIATE_LINK_NAB",
    "Westpac": "AFFILIATE_LINK_WESTPAC",
    "Wise": "AFFILIATE_LINK_WISE",
    "Remitly": "AFFILIATE_LINK_REMITLY",
    "OFX": "AFFILIATE_LINK_OFX",
    "UnitedCurrency": "AFFILIATE_LINK_UNITEDCURRENCY",
    "TravelMoneyOz": "AFFILIATE_LINK_TRAVELMONEYOZ",
    "Travelex": "AFFILIATE_LINK_TRAVELEX",
}


def decode_jwt_role(token: str) -> str:
    if token.count(".") < 2:
        return "unknown"
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8")
        return json.loads(decoded).get("role", "unknown")
    except Exception:
        return "unknown"


def is_service_role_like_key(token: str) -> bool:
    if token.startswith("sb_secret_"):
        return True
    return decode_jwt_role(token) == "service_role"


def parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_rate(value: float) -> str:
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 100:
        return f"{value:.2f}"
    return f"{value:.4f}"


def normalize_provider(provider: str) -> str:
    if provider == "United Currency":
        return "UnitedCurrency"
    return provider


def with_tracking(url: str, placement: str, currency: str) -> str:
    try:
        parsed = urlparse(url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["utm_source"] = "ausmoneysaver"
        params["utm_medium"] = "affiliate"
        params["utm_campaign"] = "best-rate"
        params["utm_content"] = placement
        params["utm_term"] = currency
        new_query = urlencode(params)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url


def provider_link(provider: str, currency: str) -> str:
    key = normalize_provider(provider)
    override = os.getenv(PROVIDER_AFFILIATE_ENV.get(key, ""), "").strip()
    base = override or PROVIDER_FALLBACK_LINKS.get(key, "https://wise.com/au")
    return with_tracking(base, "email-alert", currency)


def supabase_headers(service_key: str) -> dict[str, str]:
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def fetch_active_alerts(supabase_url: str, service_key: str) -> list[dict]:
    all_rows: list[dict] = []
    limit = 500
    offset = 0
    headers = supabase_headers(service_key)

    while True:
        endpoint = (
            "rate_alerts"
            "?select=id,email,currency,target_rate,direction,last_notified_at,is_active,created_at"
            "&is_active=eq.true"
            "&order=created_at.asc"
            f"&limit={limit}&offset={offset}"
        )
        url = f"{supabase_url.rstrip('/')}/rest/v1/{endpoint}"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        rows = response.json()
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < limit:
            break
        offset += limit

    return all_rows


def fetch_best_send_rates(supabase_url: str, service_key: str) -> dict[str, dict]:
    endpoint = (
        "latest_exchange_rates"
        "?select=provider,currency,send_rate,scraped_at"
        "&send_rate=not.is.null"
        "&limit=5000"
    )
    url = f"{supabase_url.rstrip('/')}/rest/v1/{endpoint}"
    response = requests.get(url, headers=supabase_headers(service_key), timeout=30)
    response.raise_for_status()
    rows = response.json()

    best_by_currency: dict[str, dict] = {}
    for row in rows:
        currency = row.get("currency")
        provider = normalize_provider(row.get("provider", ""))
        rate = row.get("send_rate")
        scraped_at = row.get("scraped_at")
        if not currency or rate is None:
            continue
        current = best_by_currency.get(currency)
        if current is None or rate > current["send_rate"]:
            best_by_currency[currency] = {
                "provider": provider,
                "send_rate": float(rate),
                "scraped_at": scraped_at,
            }
    return best_by_currency


def mark_notified(supabase_url: str, service_key: str, alert_id: int, notified_at: str) -> None:
    endpoint = f"rate_alerts?id=eq.{alert_id}"
    url = f"{supabase_url.rstrip('/')}/rest/v1/{endpoint}"
    headers = supabase_headers(service_key)
    headers["Prefer"] = "return=minimal"
    response = requests.patch(
        url,
        headers=headers,
        json={"last_notified_at": notified_at},
        timeout=30,
    )
    response.raise_for_status()


def send_resend_email(
    resend_api_key: str,
    from_email: str,
    to_email: str,
    subject: str,
    html: str,
    text: str,
) -> tuple[bool, str]:
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html,
            "text": text,
        },
        timeout=30,
    )
    if response.ok:
        payload = response.json()
        return True, str(payload.get("id", "ok"))
    detail = ""
    try:
        body = response.json()
        detail = body.get("message") or body.get("name") or ""
    except Exception:
        detail = response.text[:300]
    return False, detail or f"HTTP {response.status_code}"


def is_triggered(direction: str, best_rate: float, target_rate: float) -> bool:
    if direction == "lte":
        return best_rate <= target_rate
    return best_rate >= target_rate


def compose_email(
    email: str,
    currency: str,
    target_rate: float,
    direction: str,
    best_rate: float,
    best_provider: str,
    provider_href: str,
    site_url: str,
) -> tuple[str, str, str]:
    compare_text = "at or above" if direction != "lte" else "at or below"
    subject = f"[AusMoneySaver] {currency} target hit ({fmt_rate(best_rate)})"
    html = (
        f"<p>Hello {email},</p>"
        f"<p>Your alert was triggered for <strong>{currency}</strong>.</p>"
        f"<ul>"
        f"<li>Target: {compare_text} {fmt_rate(target_rate)}</li>"
        f"<li>Current best send rate: <strong>{fmt_rate(best_rate)}</strong></li>"
        f"<li>Best provider right now: <strong>{best_provider}</strong></li>"
        f"</ul>"
        f"<p>"
        f"<a href=\"{provider_href}\">Open {best_provider}</a><br/>"
        f"<a href=\"{site_url}\">View full comparison</a>"
        f"</p>"
        f"<p>Data is indicative and may change quickly. Verify final rates on provider checkout.</p>"
    )
    text = (
        f"Your {currency} alert was triggered.\n"
        f"Target ({compare_text}): {fmt_rate(target_rate)}\n"
        f"Current best send rate: {fmt_rate(best_rate)}\n"
        f"Best provider: {best_provider}\n"
        f"Open provider: {provider_href}\n"
        f"Compare all: {site_url}\n"
    )
    return subject, html, text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cooldown-hours", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
    )
    if not supabase_url or not service_key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY/SUPABASE_KEY.")
        return 1
    if not is_service_role_like_key(service_key):
        role = decode_jwt_role(service_key)
        print(
            "SUPABASE_SERVICE_ROLE_KEY is invalid for alert processing. "
            f"Detected role={role!r}."
        )
        return 1

    resend_api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("ALERT_FROM_EMAIL", "").strip()
    if not resend_api_key or not from_email:
        print("RESEND_API_KEY/ALERT_FROM_EMAIL not configured. Skipping alert email step.")
        return 0

    site_url = os.getenv("PUBLIC_SITE_URL", "https://ausmoneysaver.com").strip()
    cooldown_hours = args.cooldown_hours
    if cooldown_hours is None:
        try:
            cooldown_hours = float(os.getenv("ALERT_COOLDOWN_HOURS", "24"))
        except ValueError:
            cooldown_hours = 24.0

    now = datetime.now(timezone.utc)
    cooldown = timedelta(hours=cooldown_hours)

    alerts = fetch_active_alerts(supabase_url, service_key)
    best_rates = fetch_best_send_rates(supabase_url, service_key)
    print(f"Loaded alerts: {len(alerts)}")
    print(f"Loaded currencies with rates: {len(best_rates)}")

    sent = 0
    skipped_not_triggered = 0
    skipped_cooldown = 0
    skipped_no_rate = 0
    failed = 0

    for alert in alerts:
        alert_id = alert.get("id")
        email = (alert.get("email") or "").strip()
        currency = (alert.get("currency") or "").strip().upper()
        direction = (alert.get("direction") or "gte").strip().lower()
        try:
            target_rate = float(alert.get("target_rate") or 0)
        except (TypeError, ValueError):
            target_rate = 0
        last_notified = parse_iso(alert.get("last_notified_at"))

        if not alert_id or not email or not currency or target_rate <= 0:
            failed += 1
            print(f"[WARN] Invalid alert payload skipped: {alert}")
            continue

        best = best_rates.get(currency)
        if not best:
            skipped_no_rate += 1
            continue

        best_rate = float(best["send_rate"])
        if not is_triggered(direction, best_rate, target_rate):
            skipped_not_triggered += 1
            continue

        if last_notified and now - last_notified < cooldown:
            skipped_cooldown += 1
            continue

        provider = best["provider"]
        provider_href = provider_link(provider, currency)
        compare_href = f"{site_url.rstrip('/')}/"
        subject, html, text = compose_email(
            email=email,
            currency=currency,
            target_rate=target_rate,
            direction=direction,
            best_rate=best_rate,
            best_provider=provider,
            provider_href=provider_href,
            site_url=compare_href,
        )

        if args.dry_run:
            sent += 1
            print(
                f"[DRY] Alert {alert_id} -> {email} ({currency}) "
                f"rate={fmt_rate(best_rate)} provider={provider}"
            )
            continue

        ok, info = send_resend_email(
            resend_api_key=resend_api_key,
            from_email=from_email,
            to_email=email,
            subject=subject,
            html=html,
            text=text,
        )
        if not ok:
            failed += 1
            print(f"[FAIL] Alert {alert_id} email send failed: {info}")
            continue

        try:
            mark_notified(supabase_url, service_key, int(alert_id), now.isoformat())
            sent += 1
            print(f"[OK] Alert {alert_id} sent to {email} (message={info})")
        except requests.RequestException as e:
            failed += 1
            print(f"[FAIL] Alert {alert_id} sent but update failed: {e}")

    print(
        "Summary: "
        f"sent={sent}, "
        f"not_triggered={skipped_not_triggered}, "
        f"cooldown={skipped_cooldown}, "
        f"no_rate={skipped_no_rate}, "
        f"failed={failed}"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
