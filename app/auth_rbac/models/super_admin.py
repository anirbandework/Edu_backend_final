"""Platform super-admin. The first one is seeded from .env (see scripts/migrate_security)."""
from sqlalchemy import Column, String
from ...models.base import Base


class SuperAdmin(Base):
    __tablename__ = "super_admins"

    email = Column(String(100), unique=True, nullable=False, index=True)
    phone = Column(String(20), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(50), nullable=True)
    last_name = Column(String(50), nullable=True)
    status = Column(String(20), default="active", nullable=False)
