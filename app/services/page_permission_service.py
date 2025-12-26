from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, delete
from sqlalchemy.orm import selectinload
from typing import List, Dict, Optional
from uuid import UUID

from ..models.role_management import Role, PagePermission
from ..models.shared.tenant import Tenant

class PagePermissionService:
    
    @staticmethod
    async def create_page_permission(
        db: AsyncSession,
        tenant_id: UUID,
        role_id: UUID,
        page_data: Dict
    ) -> PagePermission:
        """Create a new page permission"""
        permission = PagePermission(
            tenant_id=tenant_id,
            role_id=role_id,
            page_id=page_data.get("page_id"),
            page_name=page_data.get("page_name"),
            page_path=page_data.get("page_path"),
            page_icon=page_data.get("page_icon"),
            page_category=page_data.get("page_category"),
            can_view=page_data.get("can_view", True),
            can_create=page_data.get("can_create", False),
            can_edit=page_data.get("can_edit", False),
            can_delete=page_data.get("can_delete", False),
            can_export=page_data.get("can_export", False),
            can_import=page_data.get("can_import", False),
            custom_permissions=page_data.get("custom_permissions", {}),
            is_active=page_data.get("is_active", True)
        )
        
        db.add(permission)
        await db.commit()
        await db.refresh(permission)
        return permission
    
    @staticmethod
    async def get_role_permissions(
        db: AsyncSession,
        tenant_id: UUID,
        role_id: UUID
    ) -> List[PagePermission]:
        """Get all page permissions for a role"""
        result = await db.execute(
            select(PagePermission).where(
                and_(
                    PagePermission.tenant_id == tenant_id,
                    PagePermission.role_id == role_id,
                    PagePermission.is_active == True
                )
            ).order_by(PagePermission.page_category, PagePermission.page_name)
        )
        return result.scalars().all()
    
    @staticmethod
    async def update_role_permissions(
        db: AsyncSession,
        tenant_id: UUID,
        role_id: UUID,
        permissions_data: List[Dict]
    ) -> List[PagePermission]:
        """Update all permissions for a role"""
        # Delete existing permissions
        await db.execute(
            delete(PagePermission).where(
                and_(
                    PagePermission.tenant_id == tenant_id,
                    PagePermission.role_id == role_id
                )
            )
        )
        
        # Create new permissions
        permissions = []
        for perm_data in permissions_data:
            permission = PagePermission(
                tenant_id=tenant_id,
                role_id=role_id,
                **perm_data
            )
            db.add(permission)
            permissions.append(permission)
        
        await db.commit()
        return permissions
    
    @staticmethod
    async def seed_default_permissions(
        db: AsyncSession,
        tenant_id: UUID
    ):
        """Seed default page permissions for all roles in a tenant"""
        
        # Default pages configuration
        default_pages = [
            {
                "page_id": "dashboard",
                "page_name": "Dashboard",
                "page_path": "/dashboard",
                "page_icon": "dashboard",
                "page_category": "Main"
            },
            {
                "page_id": "profile",
                "page_name": "Profile",
                "page_path": "/profile",
                "page_icon": "person",
                "page_category": "Personal"
            },
            {
                "page_id": "classes",
                "page_name": "Classes",
                "page_path": "/classes",
                "page_icon": "class",
                "page_category": "Academic"
            },
            {
                "page_id": "attendance",
                "page_name": "Attendance",
                "page_path": "/attendance",
                "page_icon": "access_time",
                "page_category": "Academic"
            },
            {
                "page_id": "timetable",
                "page_name": "Timetable",
                "page_path": "/timetable",
                "page_icon": "schedule",
                "page_category": "Academic"
            },
            {
                "page_id": "assessments",
                "page_name": "Assessments",
                "page_path": "/assessments",
                "page_icon": "quiz",
                "page_category": "Academic"
            },
            {
                "page_id": "exams",
                "page_name": "Exams",
                "page_path": "/exams",
                "page_icon": "assignment",
                "page_category": "Academic"
            },
            {
                "page_id": "chat",
                "page_name": "Chat",
                "page_path": "/chat",
                "page_icon": "chat",
                "page_category": "Communication"
            },
            {
                "page_id": "notifications",
                "page_name": "Notifications",
                "page_path": "/notifications",
                "page_icon": "notifications",
                "page_category": "Communication"
            },
            {
                "page_id": "ai-tutor",
                "page_name": "AI Tutor",
                "page_path": "/ai-tutor",
                "page_icon": "smart_toy",
                "page_category": "AI Tools"
            },
            # Admin specific pages
            {
                "page_id": "user-management",
                "page_name": "User Management",
                "page_path": "/user-management",
                "page_icon": "people",
                "page_category": "Administration"
            },
            {
                "page_id": "role-management",
                "page_name": "Role Management",
                "page_path": "/role-management",
                "page_icon": "manage_accounts",
                "page_category": "Administration"
            },
            {
                "page_id": "system-settings",
                "page_name": "System Settings",
                "page_path": "/settings",
                "page_icon": "settings",
                "page_category": "Administration"
            }
        ]
        
        # Role-based permission templates - ALL PERMISSIONS SET TO TRUE INITIALLY
        role_permissions = {
            "admin": {
                "dashboard": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "profile": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "classes": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "attendance": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "timetable": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "assessments": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "exams": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "chat": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "notifications": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "ai-tutor": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "user-management": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "role-management": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "system-settings": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True}
            },
            "teacher": {
                "dashboard": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "profile": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "classes": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "attendance": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "timetable": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "assessments": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "exams": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "chat": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "notifications": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "ai-tutor": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True}
            },
            "student": {
                "dashboard": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "profile": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "classes": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "attendance": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "timetable": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "assessments": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "exams": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "chat": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "notifications": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True},
                "ai-tutor": {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True, "can_export": True, "can_import": True}
            }
        }
        
        # Get all roles for this tenant
        roles_result = await db.execute(
            select(Role).where(
                and_(Role.tenant_id == tenant_id, Role.is_active == True)
            )
        )
        roles = roles_result.scalars().all()
        
        for role in roles:
            role_name = role.role_name.lower()
            if role_name in role_permissions:
                permissions_config = role_permissions[role_name]
                
                for page in default_pages:
                    page_id = page["page_id"]
                    if page_id in permissions_config:
                        perm_config = permissions_config[page_id]
                        
                        permission = PagePermission(
                            tenant_id=tenant_id,
                            role_id=role.id,
                            page_id=page["page_id"],
                            page_name=page["page_name"],
                            page_path=page["page_path"],
                            page_icon=page["page_icon"],
                            page_category=page["page_category"],
                            can_view=perm_config.get("can_view", False),
                            can_create=perm_config.get("can_create", False),
                            can_edit=perm_config.get("can_edit", False),
                            can_delete=perm_config.get("can_delete", False),
                            can_export=perm_config.get("can_export", False),
                            can_import=perm_config.get("can_import", False),
                            is_active=True
                        )
                        db.add(permission)
        
        await db.commit()
    
    @staticmethod
    async def get_user_accessible_pages(
        db: AsyncSession,
        tenant_id: UUID,
        role_id: UUID
    ) -> List[Dict]:
        """Get all pages accessible to a user based on their role"""
        result = await db.execute(
            select(PagePermission).where(
                and_(
                    PagePermission.tenant_id == tenant_id,
                    PagePermission.role_id == role_id,
                    PagePermission.is_active == True,
                    PagePermission.can_view == True
                )
            ).order_by(PagePermission.page_category, PagePermission.page_name)
        )
        
        permissions = result.scalars().all()
        return [
            {
                "page_id": p.page_id,
                "page_name": p.page_name,
                "page_path": p.page_path,
                "page_icon": p.page_icon,
                "page_category": p.page_category,
                "permissions": {
                    "can_view": p.can_view,
                    "can_create": p.can_create,
                    "can_edit": p.can_edit,
                    "can_delete": p.can_delete,
                    "can_export": p.can_export,
                    "can_import": p.can_import,
                    "custom": p.custom_permissions
                }
            }
            for p in permissions
        ]