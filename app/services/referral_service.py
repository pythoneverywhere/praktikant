from sqlalchemy.orm import Session

from app.core.constants import MIN_WITHDRAW_AMOUNT, WithdrawStatus
from app.repositories.promo_repository import PromoRepository
from app.repositories.referral_repository import ReferralRepository
from app.repositories.user_repository import UserRepository


class ReferralService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.refs = ReferralRepository(db)
        self.users = UserRepository(db)
        self.promos = PromoRepository(db)

    def create_referral_code(self, user_id: int, code: str) -> str:
        normalized = code.strip().upper()
        normalized = "".join(ch for ch in normalized if ch.isalnum() or ch in {"_", "-"})
        if len(normalized) < 4 or len(normalized) > 20:
            raise ValueError("Промокод должен быть от 4 до 20 символов")
        user = self.users.lock_by_id(user_id)
        if not user:
            raise LookupError("Пользователь не найден")
        if user.referral_code:
            raise ValueError("У аккаунта уже создан промокод")
        if self.users.by_referral_code(normalized):
            raise LookupError("Такой промокод уже занят")
        user.referral_code = normalized
        self.promos.ensure_code(normalized)
        self.db.commit()
        return normalized

    def bind_card(self, user_id: int, card_holder: str, bank: str | None) -> dict:
        user = self.users.by_id(user_id)
        if not user:
            raise LookupError("Пользователь не найден")
        if len(card_holder.strip()) < 2:
            raise ValueError("Укажите ФИО получателя")
        # For SBP payouts we don't store card numbers anymore.
        user.payout_card_masked = user.phone or ""
        user.payout_card_holder = card_holder.strip()
        user.payout_card_bank = (bank or "").strip() or None
        from app.core.domain import now_utc

        user.payout_card_bound_at = now_utc()
        self.db.commit()
        return {
            "sbpNumber": user.phone or "",
            "holder": user.payout_card_holder,
            "bank": user.payout_card_bank,
            "boundAt": user.payout_card_bound_at,
        }

    def summary(self, user_id: int) -> dict:
        user = self.users.by_id(user_id)
        if not user:
            raise LookupError("Пользователь не найден")
        summary = self.refs.referral_summary(user_id)
        rows = self.refs.recent_withdraw_requests(user_id, 10)
        return {
            "promoCode": user.referral_code,
            # Keep both camelCase and snake_case for compatibility.
            "invitedCount": summary["invited_count"],
            "frozenAmount": summary["frozen_amount"],
            "availableAmount": summary["available_amount"],
            "pendingWithdrawAmount": summary["pending_withdraw_amount"],
            "withdrawnAmount": summary["withdrawn_amount"],
            **summary,
            "payoutCard": {
                "sbpNumber": user.phone or "",
                "holder": user.payout_card_holder or "",
                "bank": user.payout_card_bank or "",
                "boundAt": user.payout_card_bound_at,
            }
            if user.payout_card_holder
            else None,
            "withdrawalRequests": [
                {
                    "id": r.id,
                    "amount": r.amount,
                    "status": r.status,
                    "adminNote": r.admin_note,
                    "processedAt": r.processed_at,
                    "createdAt": r.created_at,
                }
                for r in rows
            ],
            "minWithdrawAmount": MIN_WITHDRAW_AMOUNT,
        }

    def withdraw(self, user_id: int) -> dict:
        # SELECT ... FOR UPDATE: параллельные запросы выполняются по очереди, поэтому
        # вторая заявка увидит первую как pending и не задвоит сумму.
        user = self.users.lock_by_id(user_id)
        if not user:
            raise LookupError("Пользователь не найден")
        if not user.payout_card_holder:
            raise ValueError("Для вывода средств заполните реквизиты СБП в личном кабинете")
        if not user.phone:
            raise ValueError("Для вывода по СБП укажите номер телефона в профиле")
        summary = self.refs.referral_summary(user_id)
        if summary["available_amount"] < MIN_WITHDRAW_AMOUNT:
            raise ValueError(f"Минимальная сумма вывода {MIN_WITHDRAW_AMOUNT} ₽")
        if self.refs.pending_withdraw_exists(user_id):
            raise ValueError("У вас уже есть заявка на вывод в обработке")
        req = self.refs.create_withdraw_request(
            user_id=user_id,
            amount=summary["available_amount"],
            card_masked=user.phone,
            card_holder=user.payout_card_holder,
            card_bank=user.payout_card_bank,
        )
        self.db.commit()
        return {"ok": True, "requestId": req.id, "requestedAmount": req.amount}

    def process_withdrawal(self, admin_id: int, request_id: int, status: str, admin_note: str | None) -> None:
        if status not in {WithdrawStatus.APPROVED.value, WithdrawStatus.REJECTED.value}:
            raise ValueError("Допустимы только статусы approved/rejected")
        # Блокируем заявку: два админа не смогут одобрить её одновременно (двойная выплата).
        row = self.refs.by_withdraw_request_id(request_id, for_update=True)
        if not row:
            raise LookupError("Заявка на вывод не найдена")
        if row.status != WithdrawStatus.PENDING.value:
            raise ValueError("Эта заявка уже обработана")
        if status == WithdrawStatus.APPROVED.value:
            self.refs.create_payout(row.user_id, row.amount, f"Выплата по заявке #{row.id}")
        self.refs.set_withdrawal_status(row, status, admin_id, (admin_note or "").strip() or None)
        self.db.commit()
