import logging
import threading

from app.core.config import get_settings
from app.models.entities import User
from app.services.email_service import EmailProviderFactory

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Уведомления пользователю о заявках — по email (в фоне, чтобы не тормозить запрос)."""

    SUBJECT = "Уведомление — Практика Онлайн"

    def notify_user(self, user: User | None, text: str) -> None:
        if not user or not user.email:
            return
        self.notify_address(user.email, text)

    def notify_address(self, to: str | None, text: str) -> None:
        if not to:
            return
        threading.Thread(target=self._send, args=(to, text), daemon=True).start()

    def _send(self, to: str, text: str) -> None:
        try:
            provider = EmailProviderFactory.create(get_settings())
            provider.send(to=to, subject=self.SUBJECT, text=text)
        except Exception:  # noqa: BLE001 — уведомление не должно ломать основной сценарий
            logger.exception("Не удалось отправить email-уведомление на %s", to)
