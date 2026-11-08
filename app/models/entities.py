from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_email_verified", "email_verified"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    privacy_accepted_at: Mapped[datetime | None]
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    referral_code: Mapped[str | None] = mapped_column(String(32), unique=True)
    email_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    payout_card_masked: Mapped[str | None] = mapped_column(String(64))
    payout_card_holder: Mapped[str | None] = mapped_column(String(255))
    payout_card_bank: Mapped[str | None] = mapped_column(String(255))
    payout_card_bound_at: Mapped[datetime | None]
    # Увеличивается при смене/сбросе пароля, выходе со всех устройств, смене роли — старые JWT перестают действовать.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    applications: Mapped[list["Application"]] = relationship(foreign_keys="Application.user_id")


class EmailVerificationToken(Base, TimestampMixin):
    __tablename__ = "email_verification_tokens"
    __table_args__ = (Index("ix_email_verification_token_hash", "token_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class PasswordResetToken(Base, TimestampMixin):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("ix_password_reset_token_hash", "token_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class AuthStepUpToken(Base, TimestampMixin):
    __tablename__ = "auth_stepup_tokens"
    __table_args__ = (Index("ix_stepup_token_hash", "token_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    email_code_hash: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(String(128))
    fingerprint_hash: Mapped[str | None] = mapped_column(String(128))
    ip: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(16))
    # Для смены email: код отправляется на новый адрес, и токен годится только для него.
    target_email: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class TrustedDevice(Base, TimestampMixin):
    __tablename__ = "trusted_devices"
    __table_args__ = (UniqueConstraint("user_id", "fingerprint_hash", name="uq_trusted_device"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    fingerprint_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    last_ip: Mapped[str | None] = mapped_column(String(128))
    last_country: Mapped[str | None] = mapped_column(String(16))
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Application(Base, TimestampMixin):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_user_id", "user_id"),
        Index("ix_applications_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tariff: Mapped[str] = mapped_column(String(255), nullable=False)
    socials: Mapped[str] = mapped_column(Text, nullable=False)
    months: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    promo_code: Mapped[str | None] = mapped_column(String(32))
    referrer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    activated_at: Mapped[datetime | None]
    ends_at: Mapped[datetime | None]
    monthly_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_month_discount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    referral_reward: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now(), nullable=False)


class ApplicationStatusHistory(Base, TimestampMixin):
    __tablename__ = "application_status_history"
    __table_args__ = (Index("ix_status_history_application_id", "application_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(64))
    new_status: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)


class ReferralPayout(Base, TimestampMixin):
    __tablename__ = "referral_payouts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    referrer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class WithdrawalRequest(Base, TimestampMixin):
    __tablename__ = "withdrawal_requests"
    __table_args__ = (Index("ix_withdrawal_requests_status", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    card_masked: Mapped[str] = mapped_column(String(64), nullable=False)
    card_holder: Mapped[str | None] = mapped_column(String(255))
    card_bank: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    admin_note: Mapped[str | None] = mapped_column(Text)
    processed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    processed_at: Mapped[datetime | None]


class AdminAuditLog(Base, TimestampMixin):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (Index("ix_admin_audit_admin_id", "admin_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    admin_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int | None]
    meta_json: Mapped[str | None] = mapped_column(Text)


class UserActionLog(Base, TimestampMixin):
    __tablename__ = "user_action_logs"
    __table_args__ = (
        Index("ix_user_action_logs_user_id", "user_id"),
        Index("ix_user_action_logs_action", "action"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    meta_json: Mapped[str | None] = mapped_column(Text)


class PromoCodeState(Base, TimestampMixin):
    __tablename__ = "promo_code_states"
    __table_args__ = (
        Index("ix_promo_code_states_code", "code"),
        Index("ix_promo_code_states_is_frozen", "is_frozen"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    is_frozen: Mapped[bool] = mapped_column(default=False, nullable=False)
    frozen_at: Mapped[datetime | None]
    frozen_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    freeze_note: Mapped[str | None] = mapped_column(Text)
