from enum import StrEnum


class AppStatus(StrEnum):
    WAITING = "Ждёт подтверждения"
    REJECTED = "Отклонена"
    ACTIVE = "Активна"
    COMPLETED = "Завершена"


class WithdrawStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


REFERRAL_RULES = {
    "base": {"buyer_discount": 500, "referrer_reward": 1000, "weekly_price": 700, "label": "Старт"},
    "pro": {"buyer_discount": 750, "referrer_reward": 1500, "weekly_price": 1150, "label": "PRO"},
    "max": {"buyer_discount": 1000, "referrer_reward": 3500, "weekly_price": 2800, "label": "Эксперт"},
}

MIN_WITHDRAW_AMOUNT = 3000
