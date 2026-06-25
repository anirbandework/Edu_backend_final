"""Invitation (signup link) model.

Super-admin invites school authorities; authorities/teachers invite students &
teachers. Each invite is a one-time, expiring token carrying the role + tenant
the invitee will join. May reference a pre-created user (target_user_id) to
activate, or create the user on signup.
"""
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from ...models.base import Base


class Invitation(Base):
    __tablename__ = "invitations"

    # Where/what the invitee will become
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True)
    role = Column(String(20), nullable=False)  # school_authority | teacher | student

    # The link
    token = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(20), default="pending", nullable=False)  # pending | accepted | revoked
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    # Optional pre-fill / pre-created target
    phone = Column(String(20), nullable=True, index=True)
    email = Column(String(100), nullable=True)
    first_name = Column(String(50), nullable=True)
    last_name = Column(String(50), nullable=True)
    target_user_id = Column(UUID(as_uuid=True), nullable=True)  # activate this user if set

    # Audit
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_by_role = Column(String(20), nullable=True)
