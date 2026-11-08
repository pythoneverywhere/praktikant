from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings


def init_db() -> None:
    settings = get_settings()
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    # configparser трактует "%" как интерполяцию — экранируем (URL-кодированные пароли, options=...).
    cfg.set_main_option("sqlalchemy.url", settings.postgres_dsn.replace("%", "%%"))

    engine = create_engine(settings.postgres_dsn, pool_pre_ping=True)
    with engine.connect() as conn:
        inspector = inspect(conn)
        has_users = inspector.has_table("users")
        has_alembic_table = inspector.has_table("alembic_version")
        version = None
        if has_alembic_table:
            version = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()

    # Existing legacy schema without Alembic history:
    # mark initial baseline, then apply newer revisions.
    if has_users and not version:
        command.stamp(cfg, "20260422_0001")

    command.upgrade(cfg, "head")
