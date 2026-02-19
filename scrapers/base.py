from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CurrencyRate:
    currency_code: str
    send_rate: float | None = None
    receive_rate: float | None = None
    fee: float | None = None


@dataclass
class ProviderResult:
    provider: str
    provider_type: str  # "bank" or "fintech"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    rates: dict[str, CurrencyRate] = field(default_factory=dict)


TARGET_CURRENCIES = {
    "KRW": "South Korea",
    "CNY": "China",
    "INR": "India",
    "USD": "United States",
    "EUR": "Eurozone",
    "GBP": "United Kingdom",
    "JPY": "Japan",
    "NZD": "New Zealand",
    "PHP": "Philippines",
    "VND": "Vietnam",
    "IDR": "Indonesia",
    "THB": "Thailand",
    "MYR": "Malaysia",
    "TWD": "Taiwan",
    "NPR": "Nepal",
    "ZAR": "South Africa",
    "CAD": "Canada",
    "SEK": "Sweden",
    "LKR": "Sri Lanka",
    "ARS": "Argentina",
    "CLP": "Chile",
}
