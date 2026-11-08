import json

from sqlalchemy import select

from app.models.entities import UserActionLog
from app.repositories.base import BaseRepository


class UserActionRepository(BaseRepository[UserActionLog]):
    def log(self, user_id: int, action: str, meta: dict | None = None) -> None:
        self.db.add(
            UserActionLog(
                user_id=user_id,
                action=action,
                meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
            )
        )

    def list_by_user(self, user_id: int, limit: int = 50) -> list[UserActionLog]:
        stmt = (
            select(UserActionLog)
            .where(UserActionLog.user_id == user_id)
            .order_by(UserActionLog.created_at.desc(), UserActionLog.id.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())
