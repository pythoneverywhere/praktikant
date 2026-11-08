import logging
from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

INSECURE_SECRET_PREFIXES = ("change_me",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "praktikant-python"
    app_env: str = "development"
    app_port: int = Field(default=8000, validation_alias=AliasChoices("APP_PORT", "PORT"))
    app_base_url: str = "http://localhost:8000"

    postgres_dsn: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/praktikant")

    # Без значения по умолчанию: приложение не стартует, если секрет не задан.
    jwt_secret: str = ""
    jwt_expires_hours: int = 24 * 7
    cookie_name: str = "praktika_token"
    # None = автоматически: Secure, если APP_BASE_URL начинается с https://
    cookie_secure: bool | None = None

    # IP обратных прокси (через запятую), которым разрешено передавать X-Forwarded-For / CF-IPCountry.
    # Пусто = заголовкам не доверяем, берём IP TCP-соединения.
    trusted_proxies: str = ""

    admin_emails: str = ""
    # Тестовый код для локальной разработки. Работает ТОЛЬКО при REAL_SEND=false и APP_ENV != production.
    test_bypass_code: str = "335335"
    auto_complete_interval_seconds: int = 60
    run_db_migrations_on_startup: bool = False
    login_stepup_always: bool = False
    real_send: bool = False

    mail_from: str = "no-reply@praktika.local"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    unisender_api_key: str = ""
    unisender_base_url: str = "https://goapi.unisender.ru/ru/transactional/api/v1"

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def cookie_secure_effective(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_base_url.lower().startswith("https://")

    @property
    def test_bypass_enabled(self) -> bool:
        return (not self.real_send) and (not self.is_production) and bool(self.test_bypass_code.strip())

    def admin_email_set(self) -> set[str]:
        return {
            part.strip().lower()
            for part in self.admin_emails.split(",")
            if part.strip()
        }

    def trusted_proxy_set(self) -> set[str]:
        return {part.strip() for part in self.trusted_proxies.split(",") if part.strip()}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    secret = settings.jwt_secret.strip()
    if len(secret) < 32 or secret.lower().startswith(INSECURE_SECRET_PREFIXES):
        raise RuntimeError("JWT_SECRET must be a random value of at least 32 characters (not the example one).")
    if settings.is_production:
        if not settings.real_send:
            raise RuntimeError("APP_ENV=production requires REAL_SEND=true (test bypass code must be off in production).")
        if not settings.cookie_secure_effective:
            raise RuntimeError("APP_ENV=production requires HTTPS: set APP_BASE_URL=https://... or COOKIE_SECURE=true.")
    if settings.test_bypass_enabled:
        logger.warning("TEST BYPASS CODE IS ENABLED (REAL_SEND=false). Never use this configuration in production.")
    return settings
