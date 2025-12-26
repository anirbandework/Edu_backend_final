"""add_role_management_tables

Revision ID: 715d01eebed1
Revises: rbac_001
Create Date: 2025-12-26 17:02:00.094814

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '715d01eebed1'
down_revision: Union[str, None] = 'e0473961605e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create roles table
    op.create_table('roles',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, default=False),
        sa.Column('tenant_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role_name', sa.String(length=50), nullable=False),
        sa.Column('subrole', sa.String(length=50), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'role_name', 'subrole', name='uq_tenant_role_subrole')
    )
    op.create_index('idx_role_tenant_active', 'roles', ['tenant_id', 'is_active'])
    op.create_index('idx_role_name_active', 'roles', ['role_name', 'is_active'])
    op.create_index(op.f('ix_roles_id'), 'roles', ['id'])
    op.create_index(op.f('ix_roles_tenant_id'), 'roles', ['tenant_id'])
    op.create_index(op.f('ix_roles_created_at'), 'roles', ['created_at'])
    op.create_index(op.f('ix_roles_is_deleted'), 'roles', ['is_deleted'])

    # Create user_roles table
    op.create_table('user_roles',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, default=False),
        sa.Column('tenant_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_type', sa.Enum('TEACHER', 'STUDENT', 'SCHOOL_AUTHORITY', name='usertype'), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_user_single_role')
    )
    op.create_index('idx_user_role_tenant', 'user_roles', ['tenant_id', 'user_id'])
    op.create_index('idx_user_type_tenant', 'user_roles', ['user_type', 'tenant_id'])
    op.create_index(op.f('ix_user_roles_id'), 'user_roles', ['id'])
    op.create_index(op.f('ix_user_roles_tenant_id'), 'user_roles', ['tenant_id'])
    op.create_index(op.f('ix_user_roles_role_id'), 'user_roles', ['role_id'])
    op.create_index(op.f('ix_user_roles_user_id'), 'user_roles', ['user_id'])
    op.create_index(op.f('ix_user_roles_created_at'), 'user_roles', ['created_at'])
    op.create_index(op.f('ix_user_roles_is_deleted'), 'user_roles', ['is_deleted'])


def downgrade() -> None:
    op.drop_table('user_roles')
    op.drop_table('roles')
