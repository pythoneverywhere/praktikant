from datetime import UTC, datetime

from sqlalchemy import select, update

from app.models.entities import (
    AuthStepUpToken,
    EmailVerificationToken,
    PasswordResetToken,
    TrustedDevice,
)
from app.repositories.base import BaseRepository


class AuthRepository(BaseRepository[EmailVerificationToken]):
    def create_email_verification(self, token: EmailVerificationToken) -> None:
        self.db.add(token)

    def latest_email_verification_by_user(self, user_id: int) -> EmailVerificationToken | None:
        stmt = (
            select(EmailVerificationToken)
            .where(EmailVerificationToken.user_id == user_id)
            .order_by(EmailVerificationToken.id.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def email_verification_by_token_hash(self, token_hash: str) -> EmailVerificationToken | None:
        stmt = select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def create_password_reset(self, token: PasswordResetToken) -> None:
        self.db.add(token)

    def invalidate_active_password_resets(self, user_id: int) -> None:
        stmt = (
            update(PasswordResetToken)
            .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
            .values(used_at=datetime.now(tz=UTC))
        )
        self.db.execute(stmt)

    def password_reset_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        stmt = select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def create_step_up_token(self, token: AuthStepUpToken) -> None:
        self.db.add(token)

    def step_up_by_token_hash(self, token_hash: str) -> AuthStepUpToken | None:
        stmt = select(AuthStepUpToken).where(AuthStepUpToken.token_hash == token_hash).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def trusted_device(self, user_id: int, fingerprint_hash: str) -> TrustedDevice | None:
        stmt = select(TrustedDevice).where(
            TrustedDevice.user_id == user_id,
            TrustedDevice.fingerprint_hash == fingerprint_hash,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def upsert_trusted_device(
        self,
        user_id: int,
        fingerprint_hash: str,
        ip: str,
        country: str,
    ) -> None:
        existing = self.trusted_device(user_id, fingerprint_hash)
        now = datetime.now(tz=UTC)
        if existing:
            existing.last_ip = ip
            existing.last_country = country
            existing.last_seen_at = now
            return
        self.db.add(
            TrustedDevice(
                user_id=user_id,
                fingerprint_hash=fingerprint_hash,
                last_ip=ip,
                last_country=country,
                last_seen_at=now,
            )
        )
