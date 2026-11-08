import threading
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.domain import normalize_email, normalize_phone, now_utc
from app.core.request_meta import get_client_country, get_client_ip, get_device_fingerprint
from app.core.security import PasswordHasher, TokenManager
from app.models.entities import AuthStepUpToken, EmailVerificationToken, PasswordResetToken, User
from app.repositories.auth_repository import AuthRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService


class LoginAttemptsService:
    """Счётчик неудачных входов (в памяти процесса).

    Две независимые блокировки:
    - по паре IP + логин (8 ошибок -> 30 минут);
    - по логину с любых IP (20 ошибок -> 15 минут) — защита от перебора с множества адресов.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()
        self.window_seconds = 15 * 60
        self.rules = {
            "ip": {"max_fails": 8, "block_seconds": 30 * 60},
            "acct": {"max_fails": 20, "block_seconds": 15 * 60},
        }

    @staticmethod
    def keys(ip: str, identifier: str) -> list[tuple[str, str]]:
        ident = identifier.strip().lower()
        return [("ip", f"ip|{ip}|{ident}"), ("acct", f"acct|{ident}")]

    def blocked_for_seconds(self, keys: list[tuple[str, str]]) -> int:
        now = now_utc().timestamp()
        worst = 0
        with self._lock:
            for _kind, key in keys:
                entry = self._store.get(key)
                if not entry:
                    continue
                if entry["window_expires"] <= now and entry.get("blocked_until", 0) <= now:
                    self._store.pop(key, None)
                    continue
                blocked_until = entry.get("blocked_until", 0)
                if blocked_until > now:
                    worst = max(worst, max(int(blocked_until - now), 1))
        return worst

    def mark_failure(self, keys: list[tuple[str, str]]) -> None:
        now = now_utc().timestamp()
        with self._lock:
            if len(self._store) > 100_000:
                self._store = {k: v for k, v in self._store.items() if v["window_expires"] > now or v.get("blocked_until", 0) > now}
            for kind, key in keys:
                rule = self.rules[kind]
                entry = self._store.get(key)
                if not entry or entry["window_expires"] <= now:
                    entry = {"fails": 0, "window_expires": now + self.window_seconds, "blocked_until": 0}
                entry["fails"] += 1
                if entry["fails"] >= rule["max_fails"]:
                    entry["blocked_until"] = now + rule["block_seconds"]
                self._store[key] = entry

    def clear(self, keys: list[tuple[str, str]]) -> None:
        with self._lock:
            # Сбрасываем только счётчик по IP: успешный вход с одного IP не должен снимать блокировку аккаунта.
            for kind, key in keys:
                if kind == "ip":
                    self._store.pop(key, None)


class AuthService:
    EMAIL_CODE_TTL_MINUTES = 20
    RESET_TOKEN_TTL_MINUTES = 20
    STEP_UP_TTL_MINUTES = 10
    MAX_CODE_ATTEMPTS = 5
    # Хеш-заглушка для выравнивания времени ответа, когда пользователь не найден.
    _DUMMY_HASH: str | None = None

    def __init__(
        self,
        db: Session,
        settings: Settings,
        password_hasher: PasswordHasher,
        token_manager: TokenManager,
        email_service: EmailService,
        login_attempts: LoginAttemptsService,
    ) -> None:
        self.db = db
        self.settings = settings
        self.password_hasher = password_hasher
        self.token_manager = token_manager
        self.email_service = email_service
        self.login_attempts = login_attempts
        self.users = UserRepository(db)
        self.auth = AuthRepository(db)

    def _promote_if_admin_email(self, user: User) -> User:
        """Выдаёт роль admin по ADMIN_EMAILS.

        Вызывается ТОЛЬКО после того, как пользователь доказал владение ящиком user.email
        (ввёл код, отправленный именно на этот адрес). Иначе любой мог бы вписать себе
        адрес администратора и получить роль.
        """
        if user.email in self.settings.admin_email_set() and user.role != "admin":
            user.role = "admin"
            self.db.flush()
        return user

    def _register_failed_attempt(self, row) -> None:
        row.attempts = int(row.attempts or 0) + 1
        if row.attempts >= self.MAX_CODE_ATTEMPTS:
            row.used_at = now_utc()
        self._save()

    def _save(self) -> None:
        self.db.commit()

    @staticmethod
    def _is_expired(expires_at: datetime) -> bool:
        # DB rows can contain naive timestamps (without timezone),
        # while now_utc() is timezone-aware.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at < now_utc()

    def _is_valid_test_bypass_code(self, code: str | None) -> bool:
        # Тестовый код для локальной разработки: работает только при REAL_SEND=false и APP_ENV != production.
        if not self.settings.test_bypass_enabled or not code:
            return False
        return self.token_manager.safe_equals(code.strip(), self.settings.test_bypass_code.strip())

    def _code_matches(self, code: str | None, code_hash: str | None) -> bool:
        if not code or not code_hash:
            return False
        if self._is_valid_test_bypass_code(code):
            return True
        return self.token_manager.safe_equals(self.token_manager.sha256(code.strip()), code_hash)

    def _create_email_verification(self, user: User) -> None:
        token = self.token_manager.random_token(32)
        code = self.token_manager.random_code(6)
        row = EmailVerificationToken(
            user_id=user.id,
            token_hash=self.token_manager.sha256(token),
            code_hash=self.token_manager.sha256(code),
            expires_at=now_utc() + timedelta(minutes=self.EMAIL_CODE_TTL_MINUTES),
        )
        self.auth.create_email_verification(row)
        self._save()
        verify_link = f"{self.settings.app_base_url}/verify-email.html?token={token}"
        self.email_service.send_email_verification(user.email, code, verify_link, self.EMAIL_CODE_TTL_MINUTES)

    def register(self, name: str, email: str, phone: str, password: str, terms_accepted: bool) -> dict:
        if not terms_accepted:
            raise ValueError("Необходимо принять политику конфиденциальности")
        normalized_email = normalize_email(email)
        normalized_phone = normalize_phone(phone)
        if len(normalized_phone) < 10:
            raise ValueError("Введите корректный номер телефона")
        if self.users.by_email(normalized_email):
            raise LookupError("Пользователь с таким email уже зарегистрирован")
        if self.users.by_phone(normalized_phone):
            raise LookupError("Пользователь с таким номером уже зарегистрирован")

        user = User(
            name=name.strip(),
            email=normalized_email,
            phone=normalized_phone,
            # Роль admin выдаётся только после подтверждения email (см. _promote_if_admin_email).
            role="user",
            privacy_accepted_at=now_utc(),
            password_hash=self.password_hasher.hash(password),
            email_verified=False,
        )
        self.db.add(user)
        self._save()
        self._create_email_verification(user)
        return {"ok": True, "requiresEmailVerification": True}

    def verify_email_request(self, email: str | None, identifier: str | None) -> dict:
        user = None
        if email:
            user = self.users.by_email(normalize_email(email))
        elif identifier:
            parsed = normalize_email(identifier) if "@" in identifier else normalize_phone(identifier)
            user = self.users.by_identifier(parsed)
        else:
            raise ValueError("Укажите email или телефон")
        if not user or user.email_verified:
            return {"ok": True, "message": "Если email существует, письмо отправлено"}
        self._create_email_verification(user)
        return {"ok": True, "message": "Письмо с кодом подтверждения отправлено"}

    def verify_email_confirm(self, token: str | None, code: str | None, email: str | None, identifier: str | None) -> User:
        invalid = "Код/ссылка недействительны или устарели"
        row = None
        if token:
            row = self.auth.email_verification_by_token_hash(self.token_manager.sha256(token.strip()))
            if not row or row.used_at or self._is_expired(row.expires_at):
                raise LookupError(invalid)
        else:
            if not code:
                raise ValueError("Передайте токен или email/телефон + код")
            user = None
            if email:
                user = self.users.by_email(normalize_email(email))
            elif identifier:
                parsed = normalize_email(identifier) if "@" in identifier else normalize_phone(identifier)
                user = self.users.by_identifier(parsed)
            if not user:
                raise LookupError(invalid)
            row = self.auth.latest_email_verification_by_user(user.id)
            if not row or row.used_at or self._is_expired(row.expires_at):
                raise LookupError(invalid)
            if not self._code_matches(code, row.code_hash):
                self._register_failed_attempt(row)
                raise LookupError(invalid)
        user = self.users.by_id(row.user_id)
        if not user:
            raise LookupError("Пользователь не найден")
        user.email_verified = True
        row.used_at = now_utc()
        self._promote_if_admin_email(user)
        self._save()
        return user

    def _needs_login_step_up(self, user: User, request: Request) -> tuple[bool, str]:
        if self.settings.login_stepup_always:
            return True, "always"
        fingerprint = get_device_fingerprint(request)
        if not fingerprint:
            return True, "missing_device_fingerprint"
        fingerprint_hash = self.token_manager.sha256(fingerprint)
        trusted = self.auth.trusted_device(user.id, fingerprint_hash)
        if not trusted:
            return True, "new_device"
        ip = get_client_ip(request)
        country = get_client_country(request)
        if (trusted.last_ip and trusted.last_ip != ip) or (trusted.last_country and trusted.last_country != country):
            return True, "new_location"
        if user.role == "admin":
            return True, "admin_access"
        return False, "none"

    def register_trusted_device(self, user_id: int, request: Request) -> None:
        fingerprint = get_device_fingerprint(request)
        if not fingerprint:
            return
        self.auth.upsert_trusted_device(
            user_id=user_id,
            fingerprint_hash=self.token_manager.sha256(fingerprint),
            ip=get_client_ip(request),
            country=get_client_country(request),
        )
        self._save()

    def create_step_up_challenge(
        self,
        user: User,
        reason: str,
        request: Request,
        requires_email_code: bool = True,
        target_email: str | None = None,
    ) -> dict:
        token = self.token_manager.random_token(32)
        email_code = self.token_manager.random_code(6) if requires_email_code else None
        fingerprint = get_device_fingerprint(request)
        row = AuthStepUpToken(
            user_id=user.id,
            token_hash=self.token_manager.sha256(token),
            email_code_hash=self.token_manager.sha256(email_code) if email_code else None,
            reason=reason[:128],
            fingerprint_hash=self.token_manager.sha256(fingerprint) if fingerprint else None,
            ip=get_client_ip(request),
            country=get_client_country(request),
            target_email=target_email,
            expires_at=now_utc() + timedelta(minutes=self.STEP_UP_TTL_MINUTES),
        )
        self.auth.create_step_up_token(row)
        self._save()
        if email_code:
            # При смене email код уходит на НОВЫЙ адрес — так подтверждается владение им.
            self.email_service.send_step_up(target_email or user.email, email_code, self.STEP_UP_TTL_MINUTES)
        return {"stepUpToken": token, "requiresEmailCode": bool(email_code)}

    def consume_step_up(
        self,
        token: str,
        email_code: str | None,
        expected_reason_prefix: str | None,
        expected_user_id: int | None = None,
        expected_target_email: str | None = None,
    ) -> User:
        row = self.auth.step_up_by_token_hash(self.token_manager.sha256((token or "").strip()))
        if not row:
            raise LookupError("Код подтверждения не найден")
        if expected_user_id and row.user_id != expected_user_id:
            raise PermissionError("Токен не принадлежит пользователю")
        if row.used_at or self._is_expired(row.expires_at):
            raise LookupError("Срок действия кода истек, запросите новый")
        if expected_reason_prefix and not (row.reason or "").startswith(expected_reason_prefix):
            raise ValueError("Неверная цель подтверждения")
        if (row.target_email or None) != (expected_target_email or None):
            raise ValueError("Код был запрошен для другого email — запросите код заново")
        if row.email_code_hash and not self._code_matches(email_code, row.email_code_hash):
            self._register_failed_attempt(row)
            left = max(self.MAX_CODE_ATTEMPTS - int(row.attempts or 0), 0)
            if left == 0:
                raise ValueError("Неверный email-код. Попытки исчерпаны, запросите новый код")
            raise ValueError(f"Неверный email-код. Осталось попыток: {left}")
        user = self.users.by_id(row.user_id)
        if not user:
            raise LookupError("Пользователь не найден")
        row.used_at = now_utc()
        if not row.target_email:
            # Код пришёл на текущий user.email — владение ящиком подтверждено.
            self._promote_if_admin_email(user)
        self._save()
        return user

    def _dummy_verify(self, password: str) -> None:
        if AuthService._DUMMY_HASH is None:
            AuthService._DUMMY_HASH = self.password_hasher.hash("dummy-password-for-timing")
        self.password_hasher.verify(password, AuthService._DUMMY_HASH)

    def login(self, identifier: str, password: str, request: Request) -> dict:
        parsed = normalize_email(identifier) if "@" in identifier else normalize_phone(identifier)
        keys = self.login_attempts.keys(get_client_ip(request), parsed or identifier)
        blocked_seconds = self.login_attempts.blocked_for_seconds(keys)
        if blocked_seconds > 0:
            return {"blocked": True, "retryAfter": blocked_seconds}

        user = self.users.by_identifier(parsed) if parsed else None
        if not user:
            self._dummy_verify(password)
            self.login_attempts.mark_failure(keys)
            raise PermissionError("Неверные данные для входа")
        if not self.password_hasher.verify(password, user.password_hash):
            self.login_attempts.mark_failure(keys)
            raise PermissionError("Неверные данные для входа")
        if not user.email_verified:
            raise PermissionError("Подтвердите email для входа")
        self.login_attempts.clear(keys)
        required, reason = self._needs_login_step_up(user, request)
        if required:
            challenge = self.create_step_up_challenge(
                user=user,
                reason=f"login:{reason}",
                request=request,
                requires_email_code=True,
            )
            return {"stepUpRequired": True, **challenge}
        return {"stepUpRequired": False, "user": user}

    def create_password_reset_request(self, identifier: str) -> dict:
        parsed = normalize_email(identifier) if "@" in identifier else normalize_phone(identifier)
        user = self.users.by_identifier(parsed)
        generic = {"ok": True, "message": "Если аккаунт найден, письмо со ссылкой для сброса отправлено на email"}
        if not user or not user.email:
            return generic

        token = self.token_manager.random_token(32)
        self.auth.invalidate_active_password_resets(user.id)
        self.auth.create_password_reset(
            PasswordResetToken(
                user_id=user.id,
                token_hash=self.token_manager.sha256(token),
                expires_at=now_utc() + timedelta(minutes=self.RESET_TOKEN_TTL_MINUTES),
            )
        )
        self._save()
        reset_link = f"{self.settings.app_base_url}/reset-password.html?token={token}"
        self.email_service.send_password_reset(user.email, reset_link, self.RESET_TOKEN_TTL_MINUTES)
        return generic

    def confirm_password_reset(self, token: str, new_password: str) -> None:
        row = self.auth.password_reset_by_token_hash(self.token_manager.sha256(token.strip()))
        if not row or row.used_at or self._is_expired(row.expires_at):
            raise LookupError("Ссылка недействительна или устарела")
        user = self.users.by_id(row.user_id)
        if not user:
            raise LookupError("Пользователь не найден")
        user.password_hash = self.password_hasher.hash(new_password)
        # Сброс пароля завершает все активные сессии.
        user.token_version = int(user.token_version or 0) + 1
        row.used_at = now_utc()
        self.auth.invalidate_active_password_resets(user.id)
        self._save()

    def change_password(self, user_id: int, current_password: str, new_password: str, step_up_token: str, email_code: str | None) -> User:
        user = self.users.by_id(user_id)
        if not user:
            raise LookupError("Пользователь не найден")
        if not self.password_hasher.verify(current_password, user.password_hash):
            raise ValueError("Текущий пароль неверный")
        self.consume_step_up(
            token=step_up_token,
            email_code=email_code,
            expected_reason_prefix="action:password_change",
            expected_user_id=user_id,
        )
        user.password_hash = self.password_hasher.hash(new_password)
        # Завершаем остальные сессии; текущей роут выдаст новый токен.
        user.token_version = int(user.token_version or 0) + 1
        self._save()
        return user

    def bump_token_version(self, user: User) -> None:
        user.token_version = int(user.token_version or 0) + 1
        self._save()
