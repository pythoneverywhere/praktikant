from datetime import UTC, datetime

from sqlalchemy import case, func, select

from app.core.constants import AppStatus
from app.models.entities import Application, ApplicationStatusHistory
from app.repositories.base import BaseRepository


class ApplicationRepository(BaseRepository[Application]):
    def create_application(self, app: Application) -> Application:
        self.db.add(app)
        self.db.flush()
        return app

    def by_id(self, application_id: int) -> Application | None:
        return self.db.get(Application, application_id)

    def list_by_user(self, user_id: int) -> list[Application]:
        stmt = select(Application).where(Application.user_id == user_id).order_by(Application.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def first_by_user_and_status(self, user_id: int, status: str) -> Application | None:
        stmt = (
            select(Application)
            .where(Application.user_id == user_id, Application.status == status)
            .order_by(Application.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def best_subscription_by_user(self, user_id: int) -> Application | None:
        status_order = case(
            (Application.status == AppStatus.ACTIVE.value, 1),
            (Application.status == AppStatus.WAITING.value, 2),
            (Application.status == AppStatus.COMPLETED.value, 3),
            else_=4,
        )
        stmt = (
            select(Application)
            .where(Application.user_id == user_id)
            .order_by(status_order, Application.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def add_status_history(
        self,
        application_id: int,
        old_status: str | None,
        new_status: str,
        changed_by_user_id: int | None,
        note: str | None,
    ) -> None:
        self.db.add(
            ApplicationStatusHistory(
                application_id=application_id,
                old_status=old_status,
                new_status=new_status,
                changed_by_user_id=changed_by_user_id,
                note=note,
            )
        )

    def list_history_map(self, application_ids: list[int]) -> dict[int, list[ApplicationStatusHistory]]:
        if not application_ids:
            return {}
        stmt = (
            select(ApplicationStatusHistory)
            .where(ApplicationStatusHistory.application_id.in_(application_ids))
            .order_by(ApplicationStatusHistory.created_at.asc(), ApplicationStatusHistory.id.asc())
        )
        rows = list(self.db.execute(stmt).scalars().all())
        result: dict[int, list[ApplicationStatusHistory]] = {}
        for row in rows:
            result.setdefault(row.application_id, []).append(row)
        return result

    def set_status(self, app: Application, status: str, activated_at: datetime | None, ends_at: datetime | None) -> None:
        app.status = status
        app.activated_at = activated_at
        app.ends_at = ends_at
        app.updated_at = datetime.now(tz=UTC)

    def list_for_admin(
        self,
        status: str | None,
        tariff: str | None,
        promo: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        q: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Application], int]:
        stmt = select(Application)
        if status:
            stmt = stmt.where(Application.status == status)
        if tariff:
            stmt = stmt.where(Application.tariff.ilike(f"%{tariff}%"))
        if promo == "with":
            stmt = stmt.where(Application.promo_code.is_not(None), func.length(func.trim(Application.promo_code)) > 0)
        elif promo == "without":
            stmt = stmt.where((Application.promo_code.is_(None)) | (func.length(func.trim(Application.promo_code)) == 0))
        if date_from:
            stmt = stmt.where(Application.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Application.created_at <= date_to)
        if q:
            q_like = f"%{q}%"
            stmt = stmt.where(
                (Application.tariff.ilike(q_like))
                | (Application.socials.ilike(q_like))
                | (Application.promo_code.ilike(q_like))
            )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.db.execute(count_stmt).scalar_one()
        stmt = stmt.order_by(Application.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        return list(self.db.execute(stmt).scalars().all()), int(total)

    def list_expired_active(self) -> list[Application]:
        now = datetime.now(tz=UTC)
        stmt = select(Application).where(
            Application.status == AppStatus.ACTIVE.value,
            Application.ends_at.is_not(None),
            Application.ends_at <= now,
        )
        return list(self.db.execute(stmt).scalars().all())
