from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Optional
from uuid import UUID
from pydantic import BaseModel

from ..core.database import get_db
from ..services.page_permission_service import PagePermissionService
from ..models.role_management import Role, UserRole, PagePermission
from ..models.tenant_specific.school_authority import SchoolAuthority
from ..models.tenant_specific.teacher import Teacher
from ..models.tenant_specific.student import Student
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/api/rbac", tags=["RBAC Management"])

class UserRoleAssignment(BaseModel):
    user_id: UUID
    role_id: UUID

class RolePermissionUpdate(BaseModel):
    role_id: UUID
    permissions: List[Dict]

@router.get("/users")
async def get_users_for_role_assignment(
    tenant_id: UUID = Query(...),
    user_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Get all users in a tenant for role assignment"""
    try:
        users = []
        
        # Get school authorities
        if not user_type or user_type.upper() == "SCHOOL_AUTHORITY":
            auth_result = await db.execute(
                select(SchoolAuthority).where(SchoolAuthority.tenant_id == tenant_id)
            )
            for auth in auth_result.scalars().all():
                # Check if user has role
                role_result = await db.execute(
                    select(UserRole).options(selectinload(UserRole.role)).where(
                        UserRole.user_id == auth.id
                    )
                )
                user_role = role_result.scalar_one_or_none()
                
                users.append({
                    "user_id": str(auth.id),
                    "user_type": "SCHOOL_AUTHORITY",
                    "name": f"{auth.first_name} {auth.last_name}",
                    "email": auth.email,
                    "position": auth.position,
                    "current_role": {
                        "role_id": str(user_role.role_id),
                        "role_name": user_role.role.role_name,
                        "subrole": user_role.role.subrole
                    } if user_role else None
                })
        
        # Get teachers
        if not user_type or user_type.upper() == "TEACHER":
            teacher_result = await db.execute(
                select(Teacher).where(Teacher.tenant_id == tenant_id)
            )
            for teacher in teacher_result.scalars().all():
                # Check if user has role
                role_result = await db.execute(
                    select(UserRole).options(selectinload(UserRole.role)).where(
                        UserRole.user_id == teacher.id
                    )
                )
                user_role = role_result.scalar_one_or_none()
                
                users.append({
                    "user_id": str(teacher.id),
                    "user_type": "TEACHER",
                    "name": f"{teacher.first_name} {teacher.last_name}",
                    "email": teacher.email,
                    "position": teacher.position,
                    "current_role": {
                        "role_id": str(user_role.role_id),
                        "role_name": user_role.role.role_name,
                        "subrole": user_role.role.subrole
                    } if user_role else None
                })
        
        # Get students
        if not user_type or user_type.upper() == "STUDENT":
            student_result = await db.execute(
                select(Student).where(Student.tenant_id == tenant_id)
            )
            for student in student_result.scalars().all():
                # Check if user has role
                role_result = await db.execute(
                    select(UserRole).options(selectinload(UserRole.role)).where(
                        UserRole.user_id == student.id
                    )
                )
                user_role = role_result.scalar_one_or_none()
                
                users.append({
                    "user_id": str(student.id),
                    "user_type": "STUDENT",
                    "name": f"{student.first_name} {student.last_name}",
                    "email": student.email,
                    "grade_level": student.grade_level,
                    "current_role": {
                        "role_id": str(user_role.role_id),
                        "role_name": user_role.role.role_name,
                        "subrole": user_role.role.subrole
                    } if user_role else None
                })
        
        return {
            "users": users,
            "total_count": len(users)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/roles")
async def get_available_roles(
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get all available roles for a tenant"""
    try:
        roles_result = await db.execute(
            select(Role).where(
                and_(Role.tenant_id == tenant_id, Role.is_active == True)
            )
        )
        roles = roles_result.scalars().all()
        
        return {
            "roles": [
                {
                    "role_id": str(role.id),
                    "role_name": role.role_name,
                    "subrole": role.subrole,
                    "description": role.description
                }
                for role in roles
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/assign-role")
async def assign_role_to_user(
    assignment: UserRoleAssignment,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Assign a role to a user"""
    try:
        # Check if user already has a role
        existing_role = await db.execute(
            select(UserRole).where(UserRole.user_id == assignment.user_id)
        )
        existing = existing_role.scalar_one_or_none()
        
        if existing:
            # Update existing role
            existing.role_id = assignment.role_id
        else:
            # Determine user type
            user_type = "SCHOOL_AUTHORITY"  # Default
            
            # Check if it's a teacher
            teacher_check = await db.execute(
                select(Teacher).where(Teacher.id == assignment.user_id)
            )
            if teacher_check.scalar_one_or_none():
                user_type = "TEACHER"
            else:
                # Check if it's a student
                student_check = await db.execute(
                    select(Student).where(Student.id == assignment.user_id)
                )
                if student_check.scalar_one_or_none():
                    user_type = "STUDENT"
            
            # Create new role assignment
            new_role = UserRole(
                tenant_id=tenant_id,
                role_id=assignment.role_id,
                user_id=assignment.user_id,
                user_type=user_type
            )
            db.add(new_role)
        
        await db.commit()
        
        return {"message": "Role assigned successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/remove-role/{user_id}")
async def remove_user_role(
    user_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Remove role from a user"""
    try:
        # Find and delete user role
        role_result = await db.execute(
            select(UserRole).where(UserRole.user_id == user_id)
        )
        user_role = role_result.scalar_one_or_none()
        
        if user_role:
            await db.delete(user_role)
            await db.commit()
            return {"message": "Role removed successfully"}
        else:
            raise HTTPException(status_code=404, detail="User role not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/role-permissions/{role_id}")
async def get_role_permissions_with_pages(
    role_id: UUID,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Get all available pages and current permissions for a role"""
    try:
        # Get current permissions for the role
        current_permissions = await PagePermissionService.get_role_permissions(
            db, tenant_id, role_id
        )
        
        # Get all available pages (from default configuration)
        all_pages = [
            {"page_id": "dashboard", "page_name": "Dashboard", "page_path": "/dashboard", "page_icon": "dashboard", "page_category": "Main"},
            {"page_id": "profile", "page_name": "Profile", "page_path": "/profile", "page_icon": "person", "page_category": "Personal"},
            {"page_id": "classes", "page_name": "Classes", "page_path": "/classes", "page_icon": "class", "page_category": "Academic"},
            {"page_id": "attendance", "page_name": "Attendance", "page_path": "/attendance", "page_icon": "access_time", "page_category": "Academic"},
            {"page_id": "timetable", "page_name": "Timetable", "page_path": "/timetable", "page_icon": "schedule", "page_category": "Academic"},
            {"page_id": "assessments", "page_name": "Assessments", "page_path": "/assessments", "page_icon": "quiz", "page_category": "Academic"},
            {"page_id": "exams", "page_name": "Exams", "page_path": "/exams", "page_icon": "assignment", "page_category": "Academic"},
            {"page_id": "chat", "page_name": "Chat", "page_path": "/chat", "page_icon": "chat", "page_category": "Communication"},
            {"page_id": "notifications", "page_name": "Notifications", "page_path": "/notifications", "page_icon": "notifications", "page_category": "Communication"},
            {"page_id": "ai-tutor", "page_name": "AI Tutor", "page_path": "/ai-tutor", "page_icon": "smart_toy", "page_category": "AI Tools"},
            {"page_id": "user-management", "page_name": "User Management", "page_path": "/user-management", "page_icon": "people", "page_category": "Administration"},
            {"page_id": "role-management", "page_name": "Role Management", "page_path": "/role-management", "page_icon": "manage_accounts", "page_category": "Administration"},
            {"page_id": "system-settings", "page_name": "System Settings", "page_path": "/settings", "page_icon": "settings", "page_category": "Administration"}
        ]
        
        # Create permission map
        permission_map = {p.page_id: p for p in current_permissions}
        
        # Build response with all pages and their current permissions
        pages_with_permissions = []
        for page in all_pages:
            current_perm = permission_map.get(page["page_id"])
            pages_with_permissions.append({
                "page_id": page["page_id"],
                "page_name": page["page_name"],
                "page_path": page["page_path"],
                "page_icon": page["page_icon"],
                "page_category": page["page_category"],
                "permissions": {
                    "can_view": current_perm.can_view if current_perm else False,
                    "can_create": current_perm.can_create if current_perm else False,
                    "can_edit": current_perm.can_edit if current_perm else False,
                    "can_delete": current_perm.can_delete if current_perm else False,
                    "can_export": current_perm.can_export if current_perm else False,
                    "can_import": current_perm.can_import if current_perm else False
                }
            })
        
        return {
            "pages": pages_with_permissions,
            "total_pages": len(pages_with_permissions)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/update-role-permissions")
async def update_role_permissions(
    update_data: RolePermissionUpdate,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Update permissions for a role"""
    try:
        # Update role permissions
        await PagePermissionService.update_role_permissions(
            db, tenant_id, update_data.role_id, update_data.permissions
        )
        
        return {"message": "Role permissions updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))