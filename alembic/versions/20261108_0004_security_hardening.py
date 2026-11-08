"""Security hardening: token versions, code attempt counters, email-change target, keep audit log

Revision ID: 20261108_0004
Revises: 20261108_0003
Create Date: 2026-11-08 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261108_0004"
down_revision: str | None = "20261108_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "email_verification_tokens",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("auth_stepup_tokens", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("auth_stepup_tokens", sa.Column("target_email", sa.String(length=255), nullable=True))
    # Журнал действий админа сохраняется даже после удаления его аккаунта.
    op.alter_column("admin_audit_logs", "admin_user_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM admin_audit_logs WHERE admin_user_id IS NULL")
    op.alter_column("admin_audit_logs", "admin_user_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("auth_stepup_tokens", "target_email")
    op.drop_column("auth_stepup_tokens", "attempts")
    op.drop_column("email_verification_tokens", "attempts")
    op.drop_column("users", "token_version")
