"""Initial schema

Revision ID: 20260422_0001
Revises:
Create Date: 2026-04-22 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260422_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("privacy_accepted_at", sa.DateTime(), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("referral_code", sa.String(length=32), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("payout_card_masked", sa.String(length=64), nullable=True),
        sa.Column("payout_card_holder", sa.String(length=255), nullable=True),
        sa.Column("payout_card_bank", sa.String(length=255), nullable=True),
        sa.Column("payout_card_bound_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("phone"),
        sa.UniqueConstraint("referral_code"),
    )
    op.create_index("ix_users_email_verified", "users", ["email_verified"], unique=False)

    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tariff", sa.String(length=255), nullable=False),
        sa.Column("socials", sa.Text(), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("promo_code", sa.String(length=32), nullable=True),
        sa.Column("referrer_user_id", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("monthly_price", sa.Integer(), nullable=False),
        sa.Column("first_month_discount", sa.Integer(), nullable=False),
        sa.Column("total_price", sa.Integer(), nullable=False),
        sa.Column("referral_reward", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_applications_status", "applications", ["status"], unique=False)
    op.create_index("ix_applications_user_id", "applications", ["user_id"], unique=False)

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_verification_token_hash",
        "email_verification_tokens",
        ["token_hash"],
        unique=False,
    )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_password_reset_token_hash", "password_reset_tokens", ["token_hash"], unique=False)

    op.create_table(
        "auth_stepup_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("email_code_hash", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.String(length=128), nullable=True),
        sa.Column("fingerprint_hash", sa.String(length=128), nullable=True),
        sa.Column("ip", sa.String(length=128), nullable=True),
        sa.Column("country", sa.String(length=16), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stepup_token_hash", "auth_stepup_tokens", ["token_hash"], unique=False)

    op.create_table(
        "trusted_devices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint_hash", sa.String(length=128), nullable=False),
        sa.Column("last_ip", sa.String(length=128), nullable=True),
        sa.Column("last_country", sa.String(length=16), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "fingerprint_hash", name="uq_trusted_device"),
    )

    op.create_table(
        "application_status_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("old_status", sa.String(length=64), nullable=True),
        sa.Column("new_status", sa.String(length=64), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_status_history_application_id",
        "application_status_history",
        ["application_id"],
        unique=False,
    )

    op.create_table(
        "referral_payouts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("referrer_user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "withdrawal_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("card_masked", sa.String(length=64), nullable=False),
        sa.Column("card_holder", sa.String(length=255), nullable=True),
        sa.Column("card_bank", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("processed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["processed_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_withdrawal_requests_status", "withdrawal_requests", ["status"], unique=False)

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_audit_admin_id", "admin_audit_logs", ["admin_user_id"], unique=False)

    op.create_table(
        "user_action_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_action_logs_action", "user_action_logs", ["action"], unique=False)
    op.create_index("ix_user_action_logs_user_id", "user_action_logs", ["user_id"], unique=False)

    op.create_table(
        "promo_code_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("is_frozen", sa.Boolean(), nullable=False),
        sa.Column("frozen_at", sa.DateTime(), nullable=True),
        sa.Column("frozen_by_user_id", sa.Integer(), nullable=True),
        sa.Column("freeze_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["frozen_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_promo_code_states_code", "promo_code_states", ["code"], unique=False)
    op.create_index("ix_promo_code_states_is_frozen", "promo_code_states", ["is_frozen"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_promo_code_states_is_frozen", table_name="promo_code_states")
    op.drop_index("ix_promo_code_states_code", table_name="promo_code_states")
    op.drop_table("promo_code_states")

    op.drop_index("ix_user_action_logs_user_id", table_name="user_action_logs")
    op.drop_index("ix_user_action_logs_action", table_name="user_action_logs")
    op.drop_table("user_action_logs")

    op.drop_index("ix_admin_audit_admin_id", table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")

    op.drop_index("ix_withdrawal_requests_status", table_name="withdrawal_requests")
    op.drop_table("withdrawal_requests")

    op.drop_table("referral_payouts")

    op.drop_index("ix_status_history_application_id", table_name="application_status_history")
    op.drop_table("application_status_history")

    op.drop_table("trusted_devices")

    op.drop_index("ix_stepup_token_hash", table_name="auth_stepup_tokens")
    op.drop_table("auth_stepup_tokens")

    op.drop_index("ix_password_reset_token_hash", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")

    op.drop_index("ix_email_verification_token_hash", table_name="email_verification_tokens")
    op.drop_table("email_verification_tokens")

    op.drop_index("ix_applications_user_id", table_name="applications")
    op.drop_index("ix_applications_status", table_name="applications")
    op.drop_table("applications")

    op.drop_index("ix_users_email_verified", table_name="users")
    op.drop_table("users")
