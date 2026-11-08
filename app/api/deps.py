from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import PasswordHasher, TokenManager
from app.db.session import get_db
from app.repositories.user_repository import UserRepository


def settings_dep() -> Settings:
    return get_settings()


def db_dep(db: Session = Depends(get_db)) -> Session:
    return db


def token_manager_dep(settings: Settings = Depends(settings_dep)) -> TokenManager:
    return TokenManager(settings)


def password_hasher_dep() -> PasswordHasher:
    return PasswordHasher()


def current_user_id(
    request: Request,
    settings: Settings = Depends(settings_dep),
    token_manager: TokenManager = Depends(token_manager_dep),
    db: Session = Depends(db_dep),
) -> int:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Не авторизован")
    parsed = token_manager.parse_access_token(token)
    if not parsed:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия истекла, войдите снова")
    user_id, token_version = parsed
    user = UserRepository(db).by_id(user_id)
    # Удалённый пользователь или отозванная сессия (смена пароля, выход со всех устройств, смена роли).
    if not user or int(user.token_version or 0) != token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия истекла, войдите снова")
    return user_id


def current_admin_user_id(
    user_id: int = Depends(current_user_id),
    db: Session = Depends(db_dep),
) -> int:
    user = UserRepository(db).by_id(user_id)
    if not user or user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ только для администратора")
    return user_id
