from datetime import UTC, date, datetime
from math import ceil

from app.core.constants import REFERRAL_RULES


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def normalize_phone(phone: str | None) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def normalize_card_number(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def mask_card_number(number: str) -> str:
    digits = normalize_card_number(number)
    return f"**** **** **** {digits[-4:]}" if digits else ""


def detect_tariff_key(tariff: str) -> str:
    text = tariff.lower()
    if "максим" in text or "эксперт" in text:
        return "max"
    if "продвин" in text or "pro" in text:
        return "pro"
    if "базов" in text or "старт" in text:
        return "base"
    return "base"


def calculate_weeks_between(start_date: date, end_date: date) -> int:
    if end_date <= start_date:
        raise ValueError("Дата окончания практики должна быть позже даты начала")
    days = (end_date - start_date).days
    if days < 7:
        raise ValueError("Минимальный срок практики — 1 неделя")
    return ceil(days / 7)


def pricing_for_tariff(tariff: str, weeks: int, buyer_discount: int = 0) -> dict[str, int | str]:
    key = detect_tariff_key(tariff)
    rule = REFERRAL_RULES[key]
    weekly = int(rule["weekly_price"])
    total = max(weekly * weeks - buyer_discount, 0)
    return {
        "plan_label": str(rule["label"]),
        "weekly_price": weekly,
        "promo_discount": buyer_discount,
        "total_price": total,
    }


def referral_terms_for_tariff(tariff: str) -> dict[str, int]:
    key = detect_tariff_key(tariff)
    rule = REFERRAL_RULES[key]
    return {
        "buyer_discount": int(rule["buyer_discount"]),
        "referrer_reward": int(rule["referrer_reward"]),
    }


def now_utc() -> datetime:
    return datetime.now(tz=UTC)
