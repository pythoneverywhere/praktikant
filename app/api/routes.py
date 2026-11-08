from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import (
    current_admin_user_id,
    current_user_id,
    db_dep,
    password_hasher_dep,
    settings_dep,
    token_manager_dep,
)
from app.core.config import Settings
from app.core.constants import AppStatus, MIN_WITHDRAW_AMOUNT, WithdrawStatus
from app.core.domain import normalize_email, normalize_phone
from app.core.rate_limit import InMemoryRateLimiter
from app.core.request_meta import get_client_ip
from app.core.security import PasswordHasher, TokenManager
from app.repositories.admin_repository import AdminRepository
from app.repositories.user_action_repository import UserActionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.api import (
    AdminPromoCodeFreezeIn,
    AdminApplicationStatusIn,
    AdminUserUpdateIn,
    AdminWithdrawalStatusIn,
    ApplicationCreateIn,
    EmailVerifyConfirmIn,
    EmailVerifyRequestIn,
    LoginIn,
    PasswordChangeIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    ProfileUpdateIn,
    ReferralCardBindIn,
    ReferralCodeCreateIn,
    RegisterIn,
    StepUpStartIn,
    StepUpVerifyIn,
)
from app.services.admin_service import AdminService
from app.services.application_service import ApplicationService
from app.services.auth_service import AuthService, LoginAttemptsService
from app.services.email_service import EmailProviderFactory, EmailService
from app.services.notify import EmailNotifier
from app.services.referral_service import ReferralService

router = APIRouter(prefix="/api")
rate_limiter = InMemoryRateLimiter()
login_attempts = LoginAttemptsService()


ALLOWED_STEP_UP_PURPOSES = {"profile_change", "password_change"}


def limit_or_raise(request: Request, key_prefix: str, limit: int, window_seconds: int, message: str) -> None:
    ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.allow(f"{key_prefix}:{ip}", limit=limit, window_seconds=window_seconds)
    if not allowed:
        raise HTTPException(status_code=429, detail=message, headers={"Retry-After": str(retry_after)})


def build_auth_service(
    db: Session,
    settings: Settings,
    password_hasher: PasswordHasher,
    token_manager: TokenManager,
) -> AuthService:
    email_provider = EmailProviderFactory.create(settings)
    email_service = EmailService(email_provider)
    return AuthService(
        db=db,
        settings=settings,
        password_hasher=password_hasher,
        token_manager=token_manager,
        email_service=email_service,
        login_attempts=login_attempts,
    )


def set_auth_cookie(response: Response, settings: Settings, token_manager: TokenManager, user) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=token_manager.sign_access_token(user.id, int(user.token_version or 0)),
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure_effective,
        max_age=settings.jwt_expires_hours * 3600,
        path="/",
    )


def parse_admin_date(raw: str | None, suffix: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(f"{raw.strip()[:10]}{suffix}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некорректная дата фильтра (ожидается ГГГГ-ММ-ДД)") from exc


def map_user(user) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role,
        "emailVerified": bool(user.email_verified),
        "referralCode": user.referral_code,
        "payoutCard": {
            "sbpNumber": user.phone or "",
            "holder": user.payout_card_holder or "",
            "bank": user.payout_card_bank or "",
            "boundAt": user.payout_card_bound_at,
        }
        if user.payout_card_holder
        else None,
        "createdAt": user.created_at,
    }


def map_application(app, history_map: dict[int, list], user: dict | None = None) -> dict:
    history_rows = history_map.get(app.id, [])
    return {
        "id": app.id,
        "userId": app.user_id,
        "tariff": app.tariff,
        "socials": app.socials,
        "promoCode": app.promo_code,
        "referrerUserId": app.referrer_user_id,
        "weeks": app.months,
        "months": app.months,
        "status": app.status,
        "practiceStartAt": app.activated_at,
        "practiceEndAt": app.ends_at,
        "activatedAt": app.activated_at,
        "endsAt": app.ends_at,
        "createdAt": app.created_at,
        "weeklyPrice": int(app.monthly_price or 0),
        "monthlyPrice": int(app.monthly_price or 0),
        "promoDiscount": int(app.first_month_discount or 0),
        "firstMonthDiscount": int(app.first_month_discount or 0),
        "totalPrice": int(app.total_price or 0),
        "referralReward": int(app.referral_reward or 0),
        "totalAfterReferral": max(int(app.total_price or 0) - int(app.referral_reward or 0), 0),
        "user": user,
        "history": [
            {
                "id": h.id,
                "oldStatus": h.old_status,
                "newStatus": h.new_status,
                "note": h.note,
                "createdAt": h.created_at,
                "changedBy": h.changed_by_user_id,
            }
            for h in history_rows
        ],
    }


def map_user_action(row) -> dict:
    import json

    meta = {}
    if row.meta_json:
        try:
            meta = json.loads(row.meta_json)
        except ValueError:
            meta = {}
    return {
        "id": row.id,
        "userId": row.user_id,
        "action": row.action,
        "meta": meta,
        "createdAt": row.created_at,
    }


def map_promocode(owner, state, frozen_by_user=None) -> dict:
    return {
        "code": owner.referral_code,
        "owner": map_user(owner),
        "createdAt": owner.created_at,
        "isFrozen": bool(state.is_frozen) if state else False,
        "frozenAt": state.frozen_at if state else None,
        "freezeNote": state.freeze_note if state else None,
        "frozenBy": map_user(frozen_by_user) if frozen_by_user else None,
    }


def log_user_action(db: Session, user_id: int, action: str, meta: dict | None = None) -> None:
    UserActionRepository(db).log(user_id=user_id, action=action, meta=meta)
    db.commit()


@router.post("/register")
def register(
    payload: RegisterIn,
    request: Request,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
    token_manager: TokenManager = Depends(token_manager_dep),
    password_hasher: PasswordHasher = Depends(password_hasher_dep),
):
    limit_or_raise(request, "register", 10, 15 * 60, "Слишком много попыток регистрации. Попробуйте позже.")
    svc = build_auth_service(db, settings, password_hasher, token_manager)
    try:
        result = svc.register(payload.name, payload.email, payload.phone, payload.password, payload.termsAccepted)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, **result, "message": "Аккаунт создан. Подтвердите email кодом из письма."}


@router.post("/email/verify/request")
def email_verify_request(
    payload: EmailVerifyRequestIn,
    request: Request,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
    token_manager: TokenManager = Depends(token_manager_dep),
    password_hasher: PasswordHasher = Depends(password_hasher_dep),
):
    limit_or_raise(request, "email-action", 6, 15 * 60, "Слишком много email-запросов. Попробуйте позже.")
    svc = build_auth_service(db, settings, password_hasher, token_manager)
    try:
        return svc.verify_email_request(payload.email, payload.identifier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/email/verify/confirm")
def email_verify_confirm(
    payload: EmailVerifyConfirmIn,
    request: Request,
    response: Response,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
    token_manager: TokenManager = Depends(token_manager_dep),
    password_hasher: PasswordHasher = Depends(password_hasher_dep),
):
    limit_or_raise(request, "email-verify", 10, 15 * 60, "Слишком много попыток подтверждения email. Попробуйте позже.")
    svc = build_auth_service(db, settings, password_hasher, token_manager)
    try:
        user = svc.verify_email_confirm(payload.token, payload.code, payload.email, payload.identifier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_auth_cookie(response, settings, token_manager, user)
    svc.register_trusted_device(user.id, request)
    return {"ok": True, "user": map_user(user)}


@router.post("/login")
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
    token_manager: TokenManager = Depends(token_manager_dep),
    password_hasher: PasswordHasher = Depends(password_hasher_dep),
):
    limit_or_raise(request, "login-route", 30, 15 * 60, "Слишком много попыток входа. Попробуйте позже.")
    svc = build_auth_service(db, settings, password_hasher, token_manager)
    try:
        result = svc.login(payload.identifier, payload.password, request)
    except PermissionError as exc:
        message = str(exc)
        if "Подтвердите email" in message:
            raise HTTPException(status_code=403, detail=message) from exc
        raise HTTPException(status_code=401, detail=message) from exc
    if result.get("blocked"):
        raise HTTPException(
            status_code=429,
            detail="Вход временно заблокирован из-за частых неудачных попыток",
            headers={"Retry-After": str(result["retryAfter"])},
        )
    if result.get("stepUpRequired"):
        return {
            "ok": True,
            "stepUpRequired": True,
            "stepUpToken": result["stepUpToken"],
            "requiresEmailCode": result["requiresEmailCode"],
        }
    user = result["user"]
    set_auth_cookie(response, settings, token_manager, user)
    svc.register_trusted_device(user.id, request)
    return {"user": map_user(user)}


@router.post("/login/step-up/verify")
def login_step_up_verify(
    payload: StepUpVerifyIn,
    request: Request,
    response: Response,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
    token_manager: TokenManager = Depends(token_manager_dep),
    password_hasher: PasswordHasher = Depends(password_hasher_dep),
):
    limit_or_raise(request, "email-verify", 10, 15 * 60, "Слишком много попыток подтверждения email. Попробуйте позже.")
    svc = build_auth_service(db, settings, password_hasher, token_manager)
    try:
        user = svc.consume_step_up(payload.stepUpToken, payload.emailCode, "login:")
    except (ValueError, LookupError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_auth_cookie(response, settings, token_manager, user)
    svc.register_trusted_device(user.id, request)
    return {"ok": True, "user": map_user(user)}


@router.post("/logout")
def logout(response: Response, settings: Settings = Depends(settings_dep)):
    response.delete_cookie(
        settings.cookie_name, httponly=True, samesite="strict", secure=settings.cookie_secure_effective, path="/"
    )
    return {"ok": True}


@router.post("/logout/all")
def logout_all(
    response: Response,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
):
    """Выход на всех устройствах: все ранее выданные токены перестают действовать."""
    user = UserRepository(db).by_id(user_id)
    if user:
        user.token_version = int(user.token_version or 0) + 1
        db.commit()
    response.delete_cookie(
        settings.cookie_name, httponly=True, samesite="strict", secure=settings.cookie_secure_effective, path="/"
    )
    return {"ok": True}


@router.get("/me")
def me(user_id: int = Depends(current_user_id), db: Session = Depends(db_dep)):
    user = UserRepository(db).by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return {"user": map_user(user)}


@router.put("/profile")
def profile_update(
    payload: ProfileUpdateIn,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
    token_manager: TokenManager = Depends(token_manager_dep),
    password_hasher: PasswordHasher = Depends(password_hasher_dep),
):
    user_repo = UserRepository(db)
    user = user_repo.by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    normalized_email = normalize_email(payload.email)
    normalized_phone = normalize_phone(payload.phone)
    if len(normalized_phone) < 10:
        raise HTTPException(status_code=400, detail="Введите корректный номер телефона")
    email_conflict = user_repo.by_email(normalized_email)
    if email_conflict and email_conflict.id != user_id:
        raise HTTPException(status_code=409, detail="Этот email уже используется")
    phone_conflict = user_repo.by_phone(normalized_phone)
    if phone_conflict and phone_conflict.id != user_id:
        raise HTTPException(status_code=409, detail="Этот номер уже используется")
    email_changed = user.email != normalized_email
    phone_changed = (user.phone or "") != normalized_phone
    if email_changed or phone_changed:
        if not payload.stepUpToken:
            raise HTTPException(status_code=403, detail="Требуется подтверждение кодом из email")
        auth = build_auth_service(db, settings, password_hasher, token_manager)
        try:
            # При смене email код должен быть отправлен на НОВЫЙ адрес (доказательство владения им).
            auth.consume_step_up(
                token=payload.stepUpToken,
                email_code=payload.emailCode,
                expected_reason_prefix="action:profile_change",
                expected_user_id=user_id,
                expected_target_email=normalized_email if email_changed else None,
            )
        except (ValueError, LookupError, PermissionError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    old_email = user.email
    user.name = payload.name.strip()
    user.email = normalized_email
    user.phone = normalized_phone
    db.commit()
    log_user_action(
        db,
        user_id,
        "profile_updated",
        {"name": user.name, "email": user.email, "phone": user.phone},
    )
    if email_changed:
        EmailNotifier().notify_address(
            old_email,
            f"Email вашего аккаунта был изменён на {normalized_email}. "
            "Если это были не вы — срочно восстановите доступ через сброс пароля и обратитесь в поддержку.",
        )
    return {"user": map_user(user)}


@router.post("/step-up/start")
def stepup_start(
    payload: StepUpStartIn,
    request: Request,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
    token_manager: TokenManager = Depends(token_manager_dep),
    password_hasher: PasswordHasher = Depends(password_hasher_dep),
):
    limit_or_raise(request, "email-action", 6, 15 * 60, "Слишком много email-запросов. Попробуйте позже.")
    purpose = payload.purpose.strip()
    if purpose not in ALLOWED_STEP_UP_PURPOSES:
        raise HTTPException(status_code=400, detail="Некорректная цель подтверждения")
    user_repo = UserRepository(db)
    user = user_repo.by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    target_email = None
    if purpose == "profile_change" and payload.newEmail:
        new_email = normalize_email(payload.newEmail)
        if new_email != user.email:
            conflict = user_repo.by_email(new_email)
            if conflict and conflict.id != user_id:
                raise HTTPException(status_code=409, detail="Этот email уже используется")
            target_email = new_email
    auth = build_auth_service(db, settings, password_hasher, token_manager)
    result = auth.create_step_up_challenge(
        user=user,
        reason=f"action:{purpose}",
        request=request,
        requires_email_code=True,
        target_email=target_email,
    )
    if target_email:
        return {"ok": True, **result, "message": f"Код подтверждения отправлен на новый email {target_email}"}
    return {"ok": True, **result, "message": "Код подтверждения отправлен на email"}


@router.post("/password/reset/request")
def password_reset_request(
    payload: PasswordResetRequestIn,
    request: Request,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
    token_manager: TokenManager = Depends(token_manager_dep),
    password_hasher: PasswordHasher = Depends(password_hasher_dep),
):
    limit_or_raise(request, "password-reset-request", 10, 15 * 60, "Слишком много попыток сброса пароля. Попробуйте позже.")
    auth = build_auth_service(db, settings, password_hasher, token_manager)
    return auth.create_password_reset_request(payload.identifier)


@router.post("/password/reset/confirm")
def password_reset_confirm(
    payload: PasswordResetConfirmIn,
    request: Request,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
    token_manager: TokenManager = Depends(token_manager_dep),
    password_hasher: PasswordHasher = Depends(password_hasher_dep),
):
    limit_or_raise(request, "password-reset-request", 10, 15 * 60, "Слишком много попыток сброса пароля. Попробуйте позже.")
    auth = build_auth_service(db, settings, password_hasher, token_manager)
    try:
        auth.confirm_password_reset(payload.token, payload.newPassword)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": "Пароль успешно изменен"}


@router.post("/password/change")
def password_change(
    payload: PasswordChangeIn,
    request: Request,
    response: Response,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
    token_manager: TokenManager = Depends(token_manager_dep),
    password_hasher: PasswordHasher = Depends(password_hasher_dep),
):
    limit_or_raise(request, "password-change", 20, 15 * 60, "Слишком много попыток смены пароля. Попробуйте позже.")
    if not payload.stepUpToken:
        raise HTTPException(status_code=403, detail="Нужно подтверждение step-up")
    auth = build_auth_service(db, settings, password_hasher, token_manager)
    try:
        user = auth.change_password(user_id, payload.currentPassword, payload.newPassword, payload.stepUpToken, payload.emailCode)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    # Остальные сессии завершены (token_version увеличен), текущей выдаём новый токен.
    set_auth_cookie(response, settings, token_manager, user)
    log_user_action(db, user_id, "password_changed", {})
    return {"ok": True}


@router.post("/applications")
def create_application(
    payload: ApplicationCreateIn,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(db_dep),
):
    svc = ApplicationService(db)
    try:
        app = svc.create_application(
            user_id,
            payload.tariff,
            payload.socials,
            payload.startDate,
            payload.endDate,
            payload.promoCode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_user_action(
        db,
        user_id,
        "application_created",
        {
            "applicationId": app.id,
            "tariff": app.tariff,
            "weeks": app.months,
            "promoCode": app.promo_code,
            "totalPrice": int(app.total_price or 0),
        },
    )
    history_map = svc.list_history_map([app.id])
    return {"application": map_application(app, history_map)}


@router.post("/applications/{application_id}/cancel")
def cancel_application(
    application_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(db_dep),
):
    svc = ApplicationService(db)
    try:
        app = svc.cancel_waiting_application(user_id, application_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_user_action(
        db,
        user_id,
        "application_cancelled_by_user",
        {"applicationId": app.id},
    )
    history_map = svc.list_history_map([app.id])
    return {"ok": True, "application": map_application(app, history_map)}


@router.get("/my/subscription")
def my_subscription(user_id: int = Depends(current_user_id), db: Session = Depends(db_dep)):
    svc = ApplicationService(db)
    app = svc.my_subscription(user_id)
    if not app:
        return {"subscription": None}
    history_map = svc.list_history_map([app.id])
    return {"subscription": map_application(app, history_map)}


@router.get("/my/applications")
def my_applications(user_id: int = Depends(current_user_id), db: Session = Depends(db_dep)):
    svc = ApplicationService(db)
    items = svc.my_applications(user_id)
    history_map = svc.list_history_map([it.id for it in items])
    return {"applications": [map_application(it, history_map) for it in items]}


@router.post("/referral/code")
def create_referral_code(payload: ReferralCodeCreateIn, user_id: int = Depends(current_user_id), db: Session = Depends(db_dep)):
    svc = ReferralService(db)
    try:
        code = svc.create_referral_code(user_id, payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log_user_action(db, user_id, "referral_code_created", {"promoCode": code})
    return {"promoCode": code}


@router.put("/referral/card")
def bind_referral_card(payload: ReferralCardBindIn, user_id: int = Depends(current_user_id), db: Session = Depends(db_dep)):
    svc = ReferralService(db)
    try:
        card = svc.bind_card(user_id, payload.cardHolder, payload.bank)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_user_action(
        db,
        user_id,
        "referral_card_bound",
        {"sbpNumber": card["sbpNumber"], "holder": card["holder"], "bank": card["bank"]},
    )
    return {"ok": True, "payoutCard": card}


@router.get("/referral/summary")
def referral_summary(user_id: int = Depends(current_user_id), db: Session = Depends(db_dep)):
    svc = ReferralService(db)
    try:
        referral = svc.summary(user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"referral": referral}


@router.post("/referral/withdraw")
def referral_withdraw(user_id: int = Depends(current_user_id), db: Session = Depends(db_dep)):
    svc = ReferralService(db)
    try:
        result = svc.withdraw(user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    summary = svc.summary(user_id)
    log_user_action(
        db,
        user_id,
        "referral_withdraw_requested",
        {"requestedAmount": result["requestedAmount"]},
    )
    return {
        "ok": True,
        "message": "Заявка на вывод отправлена администратору",
        "requestedAmount": result["requestedAmount"],
        "referral": {**summary, "minWithdrawAmount": MIN_WITHDRAW_AMOUNT},
    }


@router.get("/admin/users")
def admin_users(
    q: str | None = None,
    role: str | None = None,
    page: int = 1,
    pageSize: int = 10,
    _admin_id: int = Depends(current_admin_user_id),
    db: Session = Depends(db_dep),
):
    svc = AdminService(db)
    page = max(1, page)
    page_size = min(100, max(1, pageSize))
    users, total = svc.list_users(q, role, page, page_size)
    return {
        "users": [map_user(u) for u in users],
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": max(1, (total + page_size - 1) // page_size),
        },
    }


@router.put("/admin/users/{user_id}")
def admin_update_user(
    user_id: int,
    payload: AdminUserUpdateIn,
    admin_id: int = Depends(current_admin_user_id),
    db: Session = Depends(db_dep),
):
    svc = AdminService(db)
    try:
        user = svc.update_user(
            user_id=user_id,
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            role=payload.role,
            referral_code=payload.referralCode,
            actor_id=admin_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": map_user(user)}


@router.get("/admin/users/{user_id}/actions")
def admin_user_actions(
    user_id: int,
    limit: int = 50,
    _admin_id: int = Depends(current_admin_user_id),
    db: Session = Depends(db_dep),
):
    svc = AdminService(db)
    try:
        rows = svc.list_user_actions(user_id, limit=min(100, max(1, limit)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"actions": [map_user_action(row) for row in rows]}


@router.get("/admin/promocodes")
def admin_promocodes(
    q: str | None = None,
    frozen: str | None = None,
    page: int = 1,
    pageSize: int = 10,
    _admin_id: int = Depends(current_admin_user_id),
    db: Session = Depends(db_dep),
):
    svc = AdminService(db)
    user_repo = UserRepository(db)
    page = max(1, page)
    page_size = min(100, max(1, pageSize))
    rows, total = svc.list_promocodes(q, frozen, page, page_size)
    frozen_by_ids = {state.frozen_by_user_id for _owner, state in rows if state and state.frozen_by_user_id}
    frozen_by_map = {uid: user_repo.by_id(uid) for uid in frozen_by_ids}
    return {
        "promocodes": [
            map_promocode(owner, state, frozen_by_map.get(state.frozen_by_user_id) if state else None)
            for owner, state in rows
        ],
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": max(1, (total + page_size - 1) // page_size),
        },
    }


@router.get("/admin/promocodes/{code}/history")
def admin_promocode_history(
    code: str,
    limit: int = 100,
    _admin_id: int = Depends(current_admin_user_id),
    db: Session = Depends(db_dep),
):
    svc = AdminService(db)
    user_repo = UserRepository(db)
    try:
        rows = svc.promocode_usage_history(code, limit=min(200, max(1, limit)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    users = {row.user_id: user_repo.by_id(row.user_id) for row in rows}
    return {
        "history": [
            {
                "applicationId": row.id,
                "status": row.status,
                "tariff": row.tariff,
                "weeks": row.months,
                "totalPrice": int(row.total_price or 0),
                "createdAt": row.created_at,
                "usedBy": map_user(users[row.user_id]) if users.get(row.user_id) else {"id": row.user_id},
            }
            for row in rows
        ]
    }


@router.patch("/admin/promocodes/{code}/freeze")
def admin_promocode_freeze(
    code: str,
    payload: AdminPromoCodeFreezeIn,
    admin_id: int = Depends(current_admin_user_id),
    db: Session = Depends(db_dep),
):
    svc = AdminService(db)
    user_repo = UserRepository(db)
    try:
        row = svc.set_promocode_frozen(code, frozen=payload.frozen, admin_id=admin_id, note=payload.note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    owner = user_repo.by_referral_code(code.strip().upper())
    frozen_by = user_repo.by_id(row.frozen_by_user_id) if row.frozen_by_user_id else None
    return {"promocode": map_promocode(owner, row, frozen_by)}


@router.delete("/admin/users/{user_id}")
def admin_delete_user(
    user_id: int,
    admin_id: int = Depends(current_admin_user_id),
    db: Session = Depends(db_dep),
):
    if user_id == admin_id:
        raise HTTPException(status_code=400, detail="Нельзя удалить собственный аккаунт администратора")
    svc = AdminService(db)
    try:
        svc.delete_user(admin_id, user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/admin/applications")
def admin_applications(
    q: str | None = None,
    status: str | None = None,
    tariff: str | None = None,
    promo: str | None = None,
    dateFrom: str | None = None,
    dateTo: str | None = None,
    page: int = 1,
    pageSize: int = 10,
    _admin_id: int = Depends(current_admin_user_id),
    db: Session = Depends(db_dep),
):
    svc = AdminService(db)
    app_svc = ApplicationService(db)
    user_repo = UserRepository(db)
    page = max(1, page)
    page_size = min(100, max(1, pageSize))
    date_from = parse_admin_date(dateFrom, "T00:00:00")
    date_to = parse_admin_date(dateTo, "T23:59:59")
    apps, total = svc.list_admin_applications(q, status, tariff, promo, date_from, date_to, page, page_size)
    history_map = app_svc.list_history_map([a.id for a in apps])
    user_map = {a.user_id: user_repo.by_id(a.user_id) for a in apps}
    return {
        "applications": [
            map_application(
                a,
                history_map,
                map_user(user_map[a.user_id]) if user_map.get(a.user_id) else {"id": a.user_id},
            )
            for a in apps
        ],
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": max(1, (total + page_size - 1) // page_size),
        },
    }


@router.patch("/admin/applications/{application_id}/status")
def admin_application_status(
    application_id: int,
    payload: AdminApplicationStatusIn,
    admin_id: int = Depends(current_admin_user_id),
    db: Session = Depends(db_dep),
):
    if payload.status not in {s.value for s in AppStatus}:
        raise HTTPException(status_code=400, detail="Некорректный статус")
    app_svc = ApplicationService(db)
    try:
        app = app_svc.set_status(application_id, payload.status, admin_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    AdminRepository(db).log_action(
        admin_id,
        "application_status_changed",
        "application",
        application_id,
        {"newStatus": payload.status},
    )
    db.commit()
    history_map = app_svc.list_history_map([app.id])
    return {"application": map_application(app, history_map)}


@router.get("/admin/withdrawals")
def admin_withdrawals(
    q: str | None = None,
    status: str | None = None,
    page: int = 1,
    pageSize: int = 10,
    _admin_id: int = Depends(current_admin_user_id),
    db: Session = Depends(db_dep),
):
    svc = AdminService(db)
    user_repo = UserRepository(db)
    page = max(1, page)
    page_size = min(100, max(1, pageSize))
    rows, total = svc.list_withdrawals(q, status, page, page_size)
    user_map = {r.user_id: user_repo.by_id(r.user_id) for r in rows}
    admin_ids = {r.processed_by_user_id for r in rows if r.processed_by_user_id}
    admin_map = {admin_id: user_repo.by_id(admin_id) for admin_id in admin_ids}

    def resolve_sbp_phone_for_admin(row) -> str:
        if row.card_masked:
            return row.card_masked
        user = user_map.get(row.user_id)
        if user and user.phone:
            return user.phone
        return ""

    return {
        "withdrawals": [
            {
                "id": r.id,
                "amount": r.amount,
                "sbp": {
                    "phone": resolve_sbp_phone_for_admin(r),
                    "holder": r.card_holder or "",
                    "bank": r.card_bank or "",
                },
                "status": r.status,
                "adminNote": r.admin_note,
                "processedAt": r.processed_at,
                "createdAt": r.created_at,
                "processedBy": (
                    admin_map[r.processed_by_user_id].name
                    if r.processed_by_user_id and admin_map.get(r.processed_by_user_id)
                    else None
                ),
                "user": map_user(user_map[r.user_id]) if user_map.get(r.user_id) else {"id": r.user_id},
            }
            for r in rows
        ],
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": max(1, (total + page_size - 1) // page_size),
        },
    }


@router.patch("/admin/withdrawals/{request_id}/status")
def admin_withdrawals_status(
    request_id: int,
    payload: AdminWithdrawalStatusIn,
    admin_id: int = Depends(current_admin_user_id),
    db: Session = Depends(db_dep),
):
    if payload.status not in {WithdrawStatus.APPROVED.value, WithdrawStatus.REJECTED.value}:
        raise HTTPException(status_code=400, detail="Допустимы только статусы approved/rejected")
    svc = ReferralService(db)
    try:
        svc.process_withdrawal(admin_id, request_id, payload.status, payload.adminNote)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AdminRepository(db).log_action(
        admin_id,
        "withdrawal_request_processed",
        "withdrawal_request",
        request_id,
        {"newStatus": payload.status},
    )
    db.commit()
    return {"ok": True}
