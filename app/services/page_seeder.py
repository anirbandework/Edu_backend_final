from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from .page_permission_service import PagePermissionService

class PageSeeder:
    
    @staticmethod
    async def seed_tenant_pages(db: AsyncSession, tenant_id: UUID):
        """Seed default pages and permissions for a tenant"""
        await PagePermissionService.seed_default_permissions(db, tenant_id)