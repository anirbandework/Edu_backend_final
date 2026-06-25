from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ...models.base import Base


class SchoolAuthority(Base):
    __tablename__ = "school_authorities"
    
    # Foreign Keys
    # Nullable: a super-admin creates an admin BEFORE they make any school; the
    # admin's active school is set on first school creation (they may own many).
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)
    
    # Basic Information
    authority_id = Column(String(20), nullable=False, index=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    # Email is OPTIONAL — login is by phone+password. Unique still holds for the
    # non-null values (Postgres allows multiple NULLs under a UNIQUE constraint).
    email = Column(String(100), nullable=True, unique=True, index=True)
    password_hash = Column(String(255), nullable=True)  # bcrypt; null = login disabled until set
    phone = Column(String(20), nullable=False)
    date_of_birth = Column(DateTime, nullable=True)
    address = Column(String(500), nullable=True)
    gender = Column(String(10), nullable=True)
    
    # Role Information
    role = Column(String(20), default="school_authority", nullable=False)
    # RBAC: assigned module/tab role (nullable; FK -> rbac_roles, SET NULL on delete).
    # Index ix_school_authorities_rbac_role is owned by database_compare/migrations.py.
    rbac_role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rbac_roles.id", ondelete="SET NULL", name="fk_authorities_rbac_role"),
        nullable=True,
    )
    status = Column(String(20), default="active", nullable=False)
    position = Column(String(100), nullable=False)
    qualification = Column(String(500))
    experience_years = Column(Integer, default=0)
    joining_date = Column(DateTime, nullable=True)
    
    # Authority Details
    authority_details = Column(JSON)
    permissions = Column(JSON)
    school_overview = Column(JSON)
    contact_info = Column(JSON)
    last_login = Column(DateTime)
    
    # Relationships
    tenant = relationship("Tenant", back_populates="authorities")
