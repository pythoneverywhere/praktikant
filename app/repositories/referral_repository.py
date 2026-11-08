from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.constants import AppStatus, WithdrawStatus
from app.models.entities import Application, ReferralPayout, WithdrawalRequest
from app.repositories.base import BaseRepository


class ReferralRepository(BaseRepository[ReferralPayout]):
    def used_promo_before(self, user_id: int) -> bool:
        stmt = (
            select(Application.id)
            .where(
                Application.user_id == user_id,
                Application.promo_code.is_not(None),
                func.length(func.trim(Application.promo_code)) > 0,
            )
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none() is not None

    def referral_summary(self, user_id: int) -> dict[str, int]:
        frozen = self.db.execute(
            select(func.coalesce(func.sum(Application.referral_reward), 0)).where(
                Application.referrer_user_id == user_id,
                Application.status.in_([AppStatus.WAITING.value, AppStatus.ACTIVE.value]),
            )
        ).scalar_one()
        available_gross = self.db.execute(
            select(func.coalesce(func.sum(Application.referral_reward), 0)).where(
                Application.referrer_user_id == user_id,
                Application.status == AppStatus.COMPLETED.value,
            )
        ).scalar_one()
        withdrawn = self.db.execute(
            select(func.coalesce(func.sum(ReferralPayout.amount), 0)).where(ReferralPayout.referrer_user_id == user_id)
        ).scalar_one()
        pending = self.db.execute(
            select(func.coalesce(func.sum(WithdrawalRequest.amount), 0)).where(
                WithdrawalRequest.user_id == user_id,
                WithdrawalRequest.status == WithdrawStatus.PENDING.value,
            )
        ).scalar_one()
        invited = self.db.execute(
            select(func.count()).select_from(Application).where(Application.referrer_user_id == user_id)
        ).scalar_one()
        available = max(int(available_gross) - int(withdrawn) - int(pending), 0)
        return {
            "invited_count": int(invited),
            "frozen_amount": int(frozen),
            "available_amount": int(available),
            "pending_withdraw_amount": int(pending),
            "withdrawn_amount": int(withdrawn),
        }

    def create_withdraw_request(
        self,
        user_id: int,
        amount: int,
        card_masked: str,
        card_holder: str | None,
        card_bank: str | None,
    ) -> WithdrawalRequest:
        row = WithdrawalRequest(
            user_id=user_id,
            amount=amount,
            card_masked=card_masked,
            card_holder=card_holder,
            card_bank=card_bank,
            status=WithdrawStatus.PENDING.value,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def pending_withdraw_exists(self, user_id: int) -> bool:
        stmt = (
            select(WithdrawalRequest.id)
            .where(
                WithdrawalRequest.user_id == user_id,
                WithdrawalRequest.status == WithdrawStatus.PENDING.value,
            )
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none() is not None

    def recent_withdraw_requests(self, user_id: int, limit: int = 10) -> list[WithdrawalRequest]:
        stmt = (
            select(WithdrawalRequest)
            .where(WithdrawalRequest.user_id == user_id)
            .order_by(WithdrawalRequest.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def by_withdraw_request_id(self, request_id: int, for_update: bool = False) -> WithdrawalRequest | None:
        if for_update:
            stmt = select(WithdrawalRequest).where(WithdrawalRequest.id == request_id).with_for_update()
            return self.db.execute(stmt).scalar_one_or_none()
        return self.db.get(WithdrawalRequest, request_id)

    def set_withdrawal_status(
        self,
        row: WithdrawalRequest,
        status: str,
        processed_by_user_id: int,
        admin_note: str | None,
    ) -> None:
        row.status = status
        row.processed_by_user_id = processed_by_user_id
        row.admin_note = admin_note
        row.processed_at = datetime.now(tz=UTC)

    def create_payout(self, user_id: int, amount: int, note: str | None) -> None:
        self.db.add(ReferralPayout(referrer_user_id=user_id, amount=amount, note=note))
