from abc import ABC, abstractmethod
import json
from urllib import error, request

from app.core.config import Settings


class EmailProvider(ABC):
    @abstractmethod
    def send(self, to: str, subject: str, text: str) -> None:
        raise NotImplementedError


class ConsoleEmailProvider(EmailProvider):
    def send(self, to: str, subject: str, text: str) -> None:
        print(f"[MAIL:FALLBACK] to={to} subject={subject}\n{text}")


class SMTPEmailProvider(EmailProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, to: str, subject: str, text: str) -> None:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._settings.mail_from
        msg["To"] = to
        msg.set_content(text)

        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if self._settings.smtp_user and self._settings.smtp_pass:
                smtp.login(self._settings.smtp_user, self._settings.smtp_pass)
            smtp.send_message(msg)


class UniSenderEmailProvider(EmailProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, to: str, subject: str, text: str) -> None:
        base_url = self._settings.unisender_base_url.rstrip("/")
        url = f"{base_url}/email/send.json"
        payload = {
            "message": {
                "recipients": [{"email": to}],
                "subject": subject,
                "from_email": self._settings.mail_from,
                "body": {"plaintext": text},
            }
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-API-KEY": self._settings.unisender_api_key,
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                raw = response.read().decode("utf-8")
                status = getattr(response, "status", 200)
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"UniSender HTTP {exc.code}: {details}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"UniSender connection error: {exc.reason}") from exc
        if status >= 400:
            raise RuntimeError(f"UniSender HTTP {status}: {raw}")


class EmailProviderFactory:
    """Factory pattern to select provider by environment."""

    @staticmethod
    def create(settings: Settings) -> EmailProvider:
        if not settings.real_send:
            return ConsoleEmailProvider()
        if settings.unisender_api_key:
            return UniSenderEmailProvider(settings)
        if settings.smtp_host:
            return SMTPEmailProvider(settings)
        return ConsoleEmailProvider()


class EmailService:
    def __init__(self, provider: EmailProvider) -> None:
        self._provider = provider

    def send_email_verification(self, to: str, code: str, verify_link: str, ttl_minutes: int) -> None:
        self._provider.send(
            to=to,
            subject="Подтверждение email — Практика Онлайн",
            text=f"Ваш код подтверждения: {code}\nКод действителен {ttl_minutes} минут.",
        )

    def send_step_up(self, to: str, code: str, ttl_minutes: int) -> None:
        self._provider.send(
            to=to,
            subject="Код подтверждения входа — Практика Онлайн",
            text=f"Ваш код подтверждения входа: {code}\nКод действует {ttl_minutes} минут.",
        )

    def send_password_reset(self, to: str, reset_link: str, ttl_minutes: int) -> None:
        self._provider.send(
            to=to,
            subject="Сброс пароля — Практика Онлайн",
            text=f"Ссылка для сброса пароля: {reset_link}\nСсылка одноразовая и действует {ttl_minutes} минут.",
        )

    def send_password_reminder(self, to: str, password: str) -> None:
        self._provider.send(
            to=to,
            subject="Восстановление пароля — Практика Онлайн",
            text=(
                "По вашему запросу создан новый пароль для входа.\n"
                f"Ваш пароль: {password}\n"
                "Рекомендуем сменить пароль после входа в личном кабинете."
            ),
        )
