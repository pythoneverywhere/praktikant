from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories.admin_repository import AdminRepository
from app.repositories.application_repository import ApplicationRepository
from app.repositories.promo_repository import PromoRepository
from app.repositories.user_action_repository import UserActionRepository
from app.repositories.user_repository import UserRepository


class AdminService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.admin = AdminRepository(db)
        self.apps = ApplicationRepository(db)
        self.users = UserRepository(db)
        self.user_actions = UserActionRepository(db)
        self.promos = PromoRepository(db)

    def list_users(self, q: str | None, role: str | None, page: int, page_size: int) -> tuple[list, int]:
        return self.admin.list_users(q, role, page, page_size)

    def update_user(
        self,
        user_id: int,
        name: str,
        email: str,
        phone: str,
        role: str,
        referral_code: str | None,
        actor_id: int,
    ):
        from app.core.domain import normalize_email, normalize_phone

        user = self.users.by_id(user_id)
        if not user:
            raise LookupError("Аккаунт не найден")
        new_role = "admin" if role == "admin" else "user"
        if user_id == actor_id and new_role != user.role:
            raise ValueError("Нельзя изменить роль собственного аккаунта")
        normalized_email = normalize_email(email)
        normalized_phone = normalize_phone(phone)
        if len(normalized_phone) < 10:
            raise ValueError("Заполните имя, email и корректный телефон")
        exists_email = self.users.by_email(normalized_email)
        if exists_email and exists_email.id != user_id:
            raise LookupError("Этот email уже используется")
        exists_phone = self.users.by_phone(normalized_phone)
        if exists_phone and exists_phone.id != user_id:
            raise LookupError("Этот номер уже используется")
        normalized_ref = None
        if referral_code:
            normalized_ref = "".join(ch for ch in referral_code.strip().upper() if ch.isalnum() or ch in {"_", "-"})
            if len(normalized_ref) < 4 or len(normalized_ref) > 20:
                raise ValueError("Промокод должен быть от 4 до 20 символов")
            ref_owner = self.users.by_referral_code(normalized_ref)
            if ref_owner and ref_owner.id != user_id:
                raise LookupError("Такой промокод уже занят")

        old_role = user.role
        old_email = user.email
        old_name = user.name
        old_phone = user.phone or ""
        old_referral_code = user.referral_code
        user.name = name.strip()
        user.email = normalized_email
        user.phone = normalized_phone
        user.role = new_role
        if old_role != new_role:
            # Смена роли завершает все сессии пользователя.
            user.token_version = int(user.token_version or 0) + 1
        user.referral_code = normalized_ref
        self.admin.log_action(
            actor_id,
            "user_updated",
            "user",
            user_id,
            {"oldRole": old_role, "newRole": user.role, "oldEmail": old_email, "newEmail": user.email},
        )
        changed_fields = {}
        if old_name != user.name:
            changed_fields["name"] = {"old": old_name, "new": user.name}
        if old_email != user.email:
            changed_fields["email"] = {"old": old_email, "new": user.email}
        if old_phone != (user.phone or ""):
            changed_fields["phone"] = {"old": old_phone, "new": user.phone or ""}
        if old_role != user.role:
            changed_fields["role"] = {"old": old_role, "new": user.role}
        if old_referral_code != user.referral_code:
            changed_fields["referralCode"] = {"old": old_referral_code, "new": user.referral_code}
        if changed_fields:
            self.user_actions.log(
                user_id=user_id,
                action="admin_updated_account",
                meta={
                    "actorAdminId": actor_id,
                    "changes": changed_fields,
                },
            )
        self.db.commit()
        return user

    def delete_user(self, actor_id: int, user_id: int):
        user = self.users.by_id(user_id)
        if not user:
            raise LookupError("Аккаунт не найден")
        self.admin.delete_user_deep(user_id)
        self.admin.log_action(actor_id, "user_deleted", "user", user_id, {})
        self.db.commit()

    def list_admin_applications(
        self,
        q: str | None,
        status: str | None,
        tariff: str | None,
        promo: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list, int]:
        return self.apps.list_for_admin(
            status=status,
            tariff=tariff,
            promo=promo,
            date_from=date_from,
            date_to=date_to,
            q=q,
            page=page,
            page_size=page_size,
        )

    def list_withdrawals(self, q: str | None, status: str | None, page: int, page_size: int) -> tuple[list, int]:
        return self.admin.list_withdrawals(q, status, page, page_size)

    def list_user_actions(self, user_id: int, limit: int = 50) -> list:
        user = self.users.by_id(user_id)
        if not user:
            raise LookupError("Аккаунт не найден")
        return self.user_actions.list_by_user(user_id, limit=limit)

    def list_promocodes(self, q: str | None, frozen: str | None, page: int, page_size: int) -> tuple[list, int]:
        return self.promos.list_codes_with_creators(q, frozen, page, page_size)

    def promocode_usage_history(self, code: str, limit: int = 100) -> list:
        owner = self.users.by_referral_code(code.strip().upper())
        if not owner:
            raise LookupError("Промокод не найден")
        return self.promos.list_usage_history(code.strip().upper(), limit=limit)

    def set_promocode_frozen(self, code: str, frozen: bool, admin_id: int, note: str | None):
        normalized = code.strip().upper()
        owner = self.users.by_referral_code(normalized)
        if not owner:
            raise LookupError("Промокод не найден")
        row = self.promos.set_frozen(normalized, frozen=frozen, admin_id=admin_id, note=note)
        self.admin.log_action(
            admin_id,
            "promocode_frozen" if frozen else "promocode_unfrozen",
            "promocode",
            row.id,
            {"code": normalized, "note": note},
        )
        self.db.commit()
        return row
