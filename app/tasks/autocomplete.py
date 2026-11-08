import asyncio
import logging

from app.core.config import Settings
from app.db.session import SessionLocal
from app.services.application_service import ApplicationService

logger = logging.getLogger(__name__)


async def run_autocomplete_loop(settings: Settings) -> None:
    while True:
        try:
            with SessionLocal() as db:
                count = ApplicationService(db).auto_complete_expired()
                if count > 0:
                    logger.info("Auto-completed applications: %s", count)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Background auto-complete failed: %s", exc)
        await asyncio.sleep(max(settings.auto_complete_interval_seconds, 10))
