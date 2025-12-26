from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, and_
from typing import List, Optional
from uuid import UUID

from ...models.role_management import Role, UserRole, PagePermission
from ...models.tenant_specific.school_authority import SchoolAuthority
from ...models.tenant_specific.teacher import Teacher
from ...models.tenant_specific.student import Student
from ...schemas.role_management.role_schemas import RoleCreate, UserRoleAssign, UserType

class RoleManagementService:
    
    @staticmethod
    async def create_role(db: AsyncSession, tenant_id: UUID, role_data: RoleCreate) -> Role:
        """Create a new role for a tenant"""
        role = Role(
            tenant_id=tenant_id,
            role_name=role_data.role_name,
            subrole=role_data.subrole,
            description=role_data.description
        )
        db.add(role)
        await db.commit()
        await db.refresh(role)
        return role
    
    @staticmethod
    async def get_tenant_roles(db: AsyncSession, tenant_id: UUID) -> List[Role]:
        """Get all active roles for a tenant"""
        result = await db.execute(
            select(Role).where(
                and_(Role.tenant_id == tenant_id, Role.is_active == True)
            )
        )
        return result.scalars().all()
    
    @staticmethod
    async def assign_role_to_user(db: AsyncSession, tenant_id: UUID, assignment: UserRoleAssign) -> dict:
        """Assign a role to a user (replaces existing role)"""
        # Check if user already has this exact role
        existing = await db.execute(
            select(UserRole).options(selectinload(UserRole.role)).where(
                and_(
                    UserRole.user_id == assignment.user_id,
                    UserRole.role_id == assignment.role_id
                )
            )
        )
        existing_role = existing.scalar_one_or_none()
        if existing_role:
            return {
                "message": f"User already has the role '{existing_role.role.role_name}' with subrole '{existing_role.role.subrole or 'None'}'",
                "already_assigned": True,
                "role": {
                    "role_name": existing_role.role.role_name,
                    "subrole": existing_role.role.subrole,
                    "description": existing_role.role.description
                }
            }
        
        # Remove any existing role for this user
        existing_any = await db.execute(
            select(UserRole).where(UserRole.user_id == assignment.user_id)
        )
        existing_any_role = existing_any.scalar_one_or_none()
        if existing_any_role:
            await db.delete(existing_any_role)
        
        # Add new role
        user_role = UserRole(
            tenant_id=tenant_id,
            role_id=assignment.role_id,
            user_id=assignment.user_id,
            user_type=assignment.user_type
        )
        db.add(user_role)
        await db.commit()
        await db.refresh(user_role)
        
        # Load role details
        await db.refresh(user_role, ['role'])
        
        return {
            "message": "Role assigned successfully",
            "already_assigned": False,
            "role": {
                "role_name": user_role.role.role_name,
                "subrole": user_role.role.subrole,
                "description": user_role.role.description
            }
        }
    
    @staticmethod
    async def get_user_roles(db: AsyncSession, tenant_id: UUID, user_id: UUID) -> Optional[UserRole]:
        """Get the single role assigned to a user"""
        result = await db.execute(
            select(UserRole).options(selectinload(UserRole.role)).join(Role).where(
                and_(
                    UserRole.tenant_id == tenant_id,
                    UserRole.user_id == user_id,
                    Role.is_active == True
                )
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_all_user_roles(db: AsyncSession, tenant_id: UUID) -> List[dict]:
        """Get all user role assignments for a tenant with user names"""
        result = await db.execute(
            select(UserRole).options(selectinload(UserRole.role)).join(Role).where(
                and_(
                    UserRole.tenant_id == tenant_id,
                    Role.is_active == True
                )
            )
        )
        user_roles = result.scalars().all()
        
        # Enrich with user names
        enriched_roles = []
        for user_role in user_roles:
            user_name = "Unknown User"
            
            if user_role.user_type.value == "SCHOOL_AUTHORITY":
                auth_result = await db.execute(select(SchoolAuthority).where(SchoolAuthority.id == user_role.user_id))
                auth = auth_result.scalar_one_or_none()
                if auth:
                    user_name = f"{auth.first_name or ''} {auth.last_name or ''}".strip() or auth.email
            elif user_role.user_type.value == "TEACHER":
                teacher_result = await db.execute(select(Teacher).where(Teacher.id == user_role.user_id))
                teacher = teacher_result.scalar_one_or_none()
                if teacher:
                    user_name = f"{teacher.first_name or ''} {teacher.last_name or ''}".strip() or teacher.email
            elif user_role.user_type.value == "STUDENT":
                student_result = await db.execute(select(Student).where(Student.id == user_role.user_id))
                student = student_result.scalar_one_or_none()
                if student:
                    user_name = f"{student.first_name or ''} {student.last_name or ''}".strip() or student.email
            
            enriched_roles.append({
                "id": user_role.id,
                "user_id": user_role.user_id,
                "user_name": user_name,
                "user_type": user_role.user_type,
                "role": user_role.role,
                "tenant_id": user_role.tenant_id
            })
        
        return enriched_roles
    
    @staticmethod
    async def bulk_assign_roles(db: AsyncSession, tenant_id: UUID, assignments: List[UserRoleAssign]) -> List[UserRole]:
        """Assign roles to multiple users (replaces existing roles)"""
        user_roles = []
        for assignment in assignments:
            # Remove existing role for this user
            existing = await db.execute(
                select(UserRole).where(UserRole.user_id == assignment.user_id)
            )
            existing_role = existing.scalar_one_or_none()
            if existing_role:
                await db.delete(existing_role)
            
            # Add new role
            user_role = UserRole(
                tenant_id=tenant_id,
                role_id=assignment.role_id,
                user_id=assignment.user_id,
                user_type=assignment.user_type
            )
            db.add(user_role)
            user_roles.append(user_role)
        
        if user_roles:
            await db.commit()
            for user_role in user_roles:
                await db.refresh(user_role)
        return user_roles
    
    @staticmethod
    async def delete_role(db: AsyncSession, tenant_id: UUID, role_id: UUID) -> bool:
        """Delete a role (soft delete by setting is_active to False)"""
        result = await db.execute(
            select(Role).where(
                and_(Role.id == role_id, Role.tenant_id == tenant_id)
            )
        )
        role = result.scalar_one_or_none()
        if role:
            role.is_active = False
            await db.commit()
            return True
        return False
    
    @staticmethod
    async def remove_user_role(db: AsyncSession, tenant_id: UUID, user_id: UUID, role_id: UUID) -> bool:
        """Remove a role from a user"""
        result = await db.execute(
            select(UserRole).where(
                and_(
                    UserRole.tenant_id == tenant_id,
                    UserRole.user_id == user_id,
                    UserRole.role_id == role_id
                )
            )
        )
        user_role = result.scalar_one_or_none()
        if user_role:
            await db.delete(user_role)
            await db.commit()
            return True
        return False