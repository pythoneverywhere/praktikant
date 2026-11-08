from datetime import UTC, datetime

from sqlalchemy import func, select

from app.models.entities import Application, PromoCodeState, User
from app.repositories.base import BaseRepository


class PromoRepository(BaseRepository[PromoCodeState]):
    def by_code(self, code: str) -> PromoCodeState | None:
        return self.db.execute(select(PromoCodeState).where(PromoCodeState.code == code)).scalar_one_or_none()

    def ensure_code(self, code: str) -> PromoCodeState:
        row = self.by_code(code)
        if row:
            return row
        row = PromoCodeState(code=code, is_frozen=False)
        self.db.add(row)
        self.db.flush()
        return row

    def set_frozen(self, code: str, frozen: bool, admin_id: int, note: str | None) -> PromoCodeState:
        row = self.ensure_code(code)
        row.is_frozen = bool(frozen)
        if frozen:
            row.frozen_at = datetime.now(tz=UTC)
            row.frozen_by_user_id = admin_id
            row.freeze_note = (note or "").strip() or None
        else:
            row.frozen_at = None
            row.frozen_by_user_id = None
            row.freeze_note = None
        return row

    def list_codes_with_creators(
        self,
        q: str | None,
        frozen: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[tuple[User, PromoCodeState | None]], int]:
        stmt = (
            select(User, PromoCodeState)
            .outerjoin(PromoCodeState, PromoCodeState.code == User.referral_code)
            .where(User.referral_code.is_not(None), func.length(func.trim(User.referral_code)) > 0)
        )
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                User.referral_code.ilike(like)
                | User.name.ilike(like)
                | User.email.ilike(like)
                | User.phone.ilike(like)
            )
        if frozen == "frozen":
            stmt = stmt.where(PromoCodeState.is_frozen.is_(True))
        elif frozen == "active":
            stmt = stmt.where((PromoCodeState.id.is_(None)) | (PromoCodeState.is_frozen.is_(False)))
        total = self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = self.db.execute(
            stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), int(total)

    def list_usage_history(self, code: str, limit: int = 100) -> list[Application]:
        stmt = (
            select(Application)
            .where(Application.promo_code == code)
            .order_by(Application.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())
