import json

from sqlalchemy import func, select

from app.models.entities import (
    AdminAuditLog,
    Application,
    ApplicationStatusHistory,
    AuthStepUpToken,
    EmailVerificationToken,
    PasswordResetToken,
    ReferralPayout,
    TrustedDevice,
    UserActionLog,
    PromoCodeState,
    User,
    WithdrawalRequest,
)
from app.repositories.base import BaseRepository


class AdminRepository(BaseRepository[AdminAuditLog]):
    def log_action(
        self,
        admin_user_id: int,
        action: str,
        entity_type: str,
        entity_id: int | None,
        meta: dict | None = None,
    ) -> None:
        self.db.add(
            AdminAuditLog(
                admin_user_id=admin_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
            )
        )

    def list_users(self, q: str | None, role: str | None, page: int, page_size: int) -> tuple[list[User], int]:
        stmt = select(User)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                User.name.ilike(like) | User.email.ilike(like) | User.phone.ilike(like) | User.referral_code.ilike(like)
            )
        if role in {"user", "admin"}:
            stmt = stmt.where(User.role == role)
        total = self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        items = self.db.execute(
            stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(items), int(total)

    def list_withdrawals(self, q: str | None, status: str | None, page: int, page_size: int) -> tuple[list[WithdrawalRequest], int]:
        stmt = select(WithdrawalRequest)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(WithdrawalRequest.card_masked.ilike(like))
        if status:
            stmt = stmt.where(WithdrawalRequest.status == status)
        total = self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        items = self.db.execute(
            stmt.order_by(WithdrawalRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(items), int(total)

    def delete_user_deep(self, user_id: int) -> None:
        user = self.db.query(User).filter(User.id == user_id).first()
        # Break references where user is a secondary actor in history rows.
        self.db.query(ApplicationStatusHistory).filter(
            ApplicationStatusHistory.changed_by_user_id == user_id
        ).update({ApplicationStatusHistory.changed_by_user_id: None}, synchronize_session=False)
        self.db.query(WithdrawalRequest).filter(
            WithdrawalRequest.processed_by_user_id == user_id
        ).update({WithdrawalRequest.processed_by_user_id: None}, synchronize_session=False)
        self.db.query(Application).filter(Application.referrer_user_id == user_id).update(
            {Application.referrer_user_id: None}, synchronize_session=False
        )
        self.db.query(PromoCodeState).filter(PromoCodeState.frozen_by_user_id == user_id).update(
            {PromoCodeState.frozen_by_user_id: None}, synchronize_session=False
        )
        # Журнал админских действий не удаляем — только отвязываем от удаляемого аккаунта.
        self.db.query(AdminAuditLog).filter(AdminAuditLog.admin_user_id == user_id).update(
            {AdminAuditLog.admin_user_id: None}, synchronize_session=False
        )

        # Delete all direct children linked by FK(user_id).
        self.db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user_id).delete(
            synchronize_session=False
        )
        self.db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user_id).delete(synchronize_session=False)
        self.db.query(AuthStepUpToken).filter(AuthStepUpToken.user_id == user_id).delete(synchronize_session=False)
        self.db.query(TrustedDevice).filter(TrustedDevice.user_id == user_id).delete(synchronize_session=False)
        self.db.query(ReferralPayout).filter(ReferralPayout.referrer_user_id == user_id).delete(synchronize_session=False)
        self.db.query(UserActionLog).filter(UserActionLog.user_id == user_id).delete(synchronize_session=False)
        if user and user.referral_code:
            self.db.query(PromoCodeState).filter(PromoCodeState.code == user.referral_code).delete(synchronize_session=False)
        self.db.query(WithdrawalRequest).filter(WithdrawalRequest.user_id == user_id).delete(synchronize_session=False)

        # Delete application history before applications.
        app_ids = select(Application.id).where(Application.user_id == user_id)
        self.db.query(ApplicationStatusHistory).filter(ApplicationStatusHistory.application_id.in_(app_ids)).delete(
            synchronize_session=False
        )
        self.db.query(Application).filter(Application.user_id == user_id).delete(synchronize_session=False)
        self.db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
