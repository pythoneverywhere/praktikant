"""Add telegram linking columns

Revision ID: 20260424_0002
Revises: 20260422_0001
Create Date: 2026-04-24 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260424_0002"
down_revision: str | None = "20260422_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("telegram_username", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("telegram_link_code", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("telegram_link_expires_at", sa.DateTime(), nullable=True))
    op.create_unique_constraint("uq_users_telegram_chat_id", "users", ["telegram_chat_id"])
    op.create_index("ix_users_telegram_link_code", "users", ["telegram_link_code"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_telegram_link_code", table_name="users")
    op.drop_constraint("uq_users_telegram_chat_id", "users", type_="unique")
    op.drop_column("users", "telegram_link_expires_at")
    op.drop_column("users", "telegram_link_code")
    op.drop_column("users", "telegram_username")
    op.drop_column("users", "telegram_chat_id")
