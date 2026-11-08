import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import Settings


class PasswordHasher:
    def __init__(self) -> None:
        # Use PBKDF2 for new hashes to avoid passlib+bcrypt backend issues,
        # but keep support for verifying legacy bcrypt hashes.
        self._pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

    def hash(self, raw_password: str) -> str:
        return self._pwd_context.hash(raw_password)

    def verify(self, raw_password: str, hashed_password: str) -> bool:
        if hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
            try:
                return bcrypt.checkpw(raw_password.encode("utf-8"), hashed_password.encode("utf-8"))
            except ValueError:
                return False
        return self._pwd_context.verify(raw_password, hashed_password)


class TokenManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def sign_access_token(self, user_id: int, token_version: int = 0) -> str:
        payload = {
            "sub": str(user_id),
            "ver": int(token_version or 0),
            "exp": datetime.now(tz=UTC) + timedelta(hours=self._settings.jwt_expires_hours),
            "iat": datetime.now(tz=UTC),
        }
        return jwt.encode(payload, self._settings.jwt_secret, algorithm="HS256")

    def parse_access_token(self, token: str) -> tuple[int, int] | None:
        """Возвращает (user_id, token_version) или None."""
        try:
            payload = jwt.decode(token, self._settings.jwt_secret, algorithms=["HS256"])
            sub = payload.get("sub")
            if not sub:
                return None
            return int(sub), int(payload.get("ver", 0))
        except (JWTError, ValueError, TypeError):
            return None

    @staticmethod
    def safe_equals(a: str | None, b: str | None) -> bool:
        if not a or not b:
            return False
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))

    @staticmethod
    def random_token(byte_len: int = 32) -> str:
        return secrets.token_hex(byte_len)

    @staticmethod
    def random_code(length: int = 6) -> str:
        max_value = 10**length - 1
        return f"{secrets.randbelow(max_value + 1):0{length}d}"

    @staticmethod
    def sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
