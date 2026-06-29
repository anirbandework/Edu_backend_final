"""InstitutionGroup — the top-level tenant grouping.

A super-admin creates an institution group; the super-admin then creates one or
more ADMINS (authorities) inside it. Those admins create ORGANISATIONS
(schools / colleges / …) that belong to the group — every admin of the group can
see/manage all of the group's organisations, but each organisation's data is
fully isolated (the admin switches the active organisation). Module-access
ceilings (the role page-pool + the admin pages) are configured per-group.
"""
from sqlalchemy import Column, String, Boolean
from ...models.base import Base


class InstitutionGroup(Base):
    __tablename__ = "institution_groups"

    name = Column(String(200), nullable=False, index=True)
    # Short human-readable code (auto-generated from the name, e.g. "ABC2026001").
    code = Column(String(20), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
