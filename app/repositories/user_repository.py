from sqlalchemy import or_, select

from app.models.entities import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def by_email(self, email: str) -> User | None:
        return self.db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    def by_phone(self, phone: str) -> User | None:
        return self.db.execute(select(User).where(User.phone == phone)).scalar_one_or_none()

    def by_identifier(self, identifier: str) -> User | None:
        stmt = select(User).where(or_(User.email == identifier, User.phone == identifier))
        return self.db.execute(stmt).scalar_one_or_none()

    def by_referral_code(self, code: str) -> User | None:
        return self.db.execute(select(User).where(User.referral_code == code)).scalar_one_or_none()

    def lock_by_id(self, user_id: int) -> User | None:
        """SELECT ... FOR UPDATE: сериализует конкурентные денежные/лимитированные операции пользователя."""
        stmt = select(User).where(User.id == user_id).with_for_update()
        return self.db.execute(stmt).scalar_one_or_none()
