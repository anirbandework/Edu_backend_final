"""add_page_permissions_table

Revision ID: add_page_permissions
Revises: 715d01eebed1
Create Date: 2025-12-26 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_page_permissions'
down_revision: Union[str, None] = '715d01eebed1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create page_permissions table
    op.create_table('page_permissions',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, default=False),
        sa.Column('tenant_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('page_id', sa.String(length=100), nullable=False),
        sa.Column('page_name', sa.String(length=100), nullable=False),
        sa.Column('page_path', sa.String(length=200), nullable=False),
        sa.Column('page_icon', sa.String(length=50), nullable=True),
        sa.Column('page_category', sa.String(length=50), nullable=True),
        sa.Column('can_view', sa.Boolean(), nullable=False, default=True),
        sa.Column('can_create', sa.Boolean(), nullable=False, default=False),
        sa.Column('can_edit', sa.Boolean(), nullable=False, default=False),
        sa.Column('can_delete', sa.Boolean(), nullable=False, default=False),
        sa.Column('can_export', sa.Boolean(), nullable=False, default=False),
        sa.Column('can_import', sa.Boolean(), nullable=False, default=False),
        sa.Column('custom_permissions', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'role_id', 'page_id', name='uq_tenant_role_page')
    )
    op.create_index('idx_page_permission_tenant_role', 'page_permissions', ['tenant_id', 'role_id'])
    op.create_index('idx_page_permission_active', 'page_permissions', ['is_active'])
    op.create_index(op.f('ix_page_permissions_id'), 'page_permissions', ['id'])
    op.create_index(op.f('ix_page_permissions_tenant_id'), 'page_permissions', ['tenant_id'])
    op.create_index(op.f('ix_page_permissions_role_id'), 'page_permissions', ['role_id'])
    op.create_index(op.f('ix_page_permissions_created_at'), 'page_permissions', ['created_at'])
    op.create_index(op.f('ix_page_permissions_is_deleted'), 'page_permissions', ['is_deleted'])


def downgrade() -> None:
    op.drop_table('page_permissions')