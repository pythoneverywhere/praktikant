from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.core.constants import AppStatus
from app.core.domain import calculate_weeks_between, now_utc, pricing_for_tariff, referral_terms_for_tariff
from app.models.entities import Application
from app.repositories.application_repository import ApplicationRepository
from app.repositories.promo_repository import PromoRepository
from app.repositories.user_repository import UserRepository
from app.services.notify import EmailNotifier


class ApplicationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.apps = ApplicationRepository(db)
        self.promos = PromoRepository(db)
        self.users = UserRepository(db)
        self.notifier = EmailNotifier()

    def create_application(
        self,
        user_id: int,
        tariff: str,
        socials: str,
        start_date_raw: str,
        end_date_raw: str,
        promo_code: str | None,
    ) -> Application:
        # Блокируем строку пользователя: параллельные запросы не создадут две заявки
        # и не применят промокод дважды.
        if not self.users.lock_by_id(user_id):
            raise ValueError("Пользователь не найден")
        existing_active = self.apps.first_by_user_and_status(user_id, AppStatus.ACTIVE.value)
        if existing_active:
            raise ValueError("У вас уже есть активная практика. Новую заявку можно создать после завершения текущей.")
        existing_waiting = self.apps.first_by_user_and_status(user_id, AppStatus.WAITING.value)
        if existing_waiting:
            raise ValueError("У вас уже есть активная заявка в ожидании. Отзовите ее или дождитесь решения.")

        normalized_tariff = tariff.strip()
        normalized_socials = socials.strip()
        if not normalized_socials:
            raise ValueError("Укажите соцсети для связи")
        try:
            start_date = date.fromisoformat((start_date_raw or "").strip())
            end_date = date.fromisoformat((end_date_raw or "").strip())
        except ValueError as exc:
            raise ValueError("Укажите корректные даты практики") from exc
        today = now_utc().date()
        if start_date < (today - timedelta(days=7)):
            raise ValueError("Дата начала может быть задним числом не более чем на 7 дней")
        weeks = calculate_weeks_between(start_date, end_date)
        if weeks > 104:
            raise ValueError("Срок практики не должен превышать 104 недель")
        normalized_promo = (promo_code or "").strip().upper() or None

        referrer = None
        buyer_discount = 0
        referrer_reward = 0
        if normalized_promo:
            if weeks < 4:
                raise ValueError("Промокод доступен только при оформлении от 4 недель")
            promo_state = self.promos.by_code(normalized_promo)
            if promo_state and promo_state.is_frozen:
                raise ValueError("Этот промокод временно заморожен администратором")
            from app.repositories.referral_repository import ReferralRepository

            refs = ReferralRepository(self.db)
            if refs.used_promo_before(user_id):
                raise ValueError("Промокод можно применить только один раз для аккаунта")
            referrer = self.users.by_referral_code(normalized_promo)
            if not referrer:
                raise ValueError("Промокод не найден")
            if referrer.id == user_id:
                raise ValueError("Нельзя применять собственный промокод")
            terms = referral_terms_for_tariff(normalized_tariff)
            buyer_discount = int(terms["buyer_discount"])
            referrer_reward = int(terms["referrer_reward"])

        pricing = pricing_for_tariff(normalized_tariff, weeks, buyer_discount)
        app = self.apps.create_application(
            Application(
                user_id=user_id,
                tariff=str(pricing["plan_label"]),
                socials=normalized_socials,
                months=weeks,
                status=AppStatus.WAITING.value,
                promo_code=normalized_promo,
                referrer_user_id=referrer.id if referrer else None,
                activated_at=datetime.combine(start_date, time.min, tzinfo=UTC),
                ends_at=datetime.combine(end_date, time.max, tzinfo=UTC),
                monthly_price=int(pricing["weekly_price"]),
                first_month_discount=int(pricing["promo_discount"]),
                total_price=int(pricing["total_price"]),
                referral_reward=referrer_reward,
            )
        )
        self.apps.add_status_history(
            application_id=app.id,
            old_status=None,
            new_status=AppStatus.WAITING.value,
            changed_by_user_id=user_id,
            note="Заявка создана пользователем",
        )
        self.db.commit()
        self.db.refresh(app)
        self.notifier.notify_user(
            self.users.by_id(user_id),
            (
                "📝 Ваша заявка на практику создана.\n"
                f"Статус: {app.status}\n"
                f"Тариф: {app.tariff}\n"
                f"Период: {start_date.isoformat()} → {end_date.isoformat()}"
            ),
        )
        return app

    def cancel_waiting_application(self, user_id: int, application_id: int) -> Application:
        self.users.lock_by_id(user_id)
        app = self.apps.by_id(application_id)
        if not app or app.user_id != user_id:
            raise LookupError("Заявка не найдена")
        if app.status != AppStatus.WAITING.value:
            raise ValueError("Отозвать можно только заявку в статусе ожидания")

        old = app.status
        self.apps.set_status(app, AppStatus.REJECTED.value, app.activated_at, app.ends_at)
        self.apps.add_status_history(
            application_id=app.id,
            old_status=old,
            new_status=AppStatus.REJECTED.value,
            changed_by_user_id=user_id,
            note="Заявка отозвана пользователем",
        )
        self.db.commit()
        self.db.refresh(app)
        self.notifier.notify_user(
            self.users.by_id(app.user_id),
            "🛑 Вы отозвали заявку на практику.",
        )
        return app

    def my_subscription(self, user_id: int) -> Application | None:
        return self.apps.best_subscription_by_user(user_id)

    def my_applications(self, user_id: int) -> list[Application]:
        return self.apps.list_by_user(user_id)

    def set_status(self, application_id: int, new_status: str, changed_by_user_id: int) -> Application:
        app = self.apps.by_id(application_id)
        if not app:
            raise LookupError("Заявка не найдена")
        if new_status == app.status:
            return app
        activated_at = app.activated_at
        ends_at = app.ends_at
        if new_status == AppStatus.ACTIVE.value:
            activated_at = app.activated_at or now_utc()
            ends_at = app.ends_at or now_utc()
        elif new_status == AppStatus.COMPLETED.value and not ends_at:
            ends_at = now_utc()
        old = app.status
        self.apps.set_status(app, new_status, activated_at, ends_at)
        self.apps.add_status_history(
            application_id=app.id,
            old_status=old,
            new_status=new_status,
            changed_by_user_id=changed_by_user_id,
            note="Статус изменен администратором",
        )
        self.db.commit()
        self.db.refresh(app)
        self.notifier.notify_user(
            self.users.by_id(app.user_id),
            (
                "🔔 Изменение статуса заявки.\n"
                f"Было: {old}\n"
                f"Стало: {new_status}"
            ),
        )
        return app

    def list_history_map(self, app_ids: list[int]) -> dict:
        return self.apps.list_history_map(app_ids)

    def auto_complete_expired(self) -> int:
        rows = self.apps.list_expired_active()
        for app in rows:
            self.apps.set_status(app, AppStatus.COMPLETED.value, app.activated_at, now_utc())
            self.apps.add_status_history(
                application_id=app.id,
                old_status=AppStatus.ACTIVE.value,
                new_status=AppStatus.COMPLETED.value,
                changed_by_user_id=None,
                note="Автоматическое завершение по сроку",
            )
        self.db.commit()
        for app in rows:
            self.notifier.notify_user(
                self.users.by_id(app.user_id),
                "✅ Ваша практика автоматически завершена по дате окончания.",
            )
        return len(rows)
