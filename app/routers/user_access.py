from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from ..core.database import get_db
from ..models.tenant_specific.school_authority import SchoolAuthority
from ..models.tenant_specific.teacher import Teacher
from ..models.tenant_specific.student import Student

router = APIRouter(prefix="/api/v1/user", tags=["User Access"])

@router.get("/{user_id}/access")
async def get_user_access(user_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get user role and basic info (simplified login endpoint)"""
    
    # Check if user is school authority (admin)
    result = await db.execute(select(SchoolAuthority).where(SchoolAuthority.id == user_id))
    admin = result.scalar_one_or_none()
    if admin:
        return {
            "user_id": str(user_id),
            "role": "admin",
            "tenant_id": str(admin.tenant_id),
            "pages": ["dashboard", "student-management", "teacher-management", "reports"]
        }
    
    # Check if user is teacher
    result = await db.execute(select(Teacher).where(Teacher.id == user_id))
    teacher = result.scalar_one_or_none()
    if teacher:
        return {
            "user_id": str(user_id),
            "role": "teacher", 
            "tenant_id": str(teacher.tenant_id),
            "pages": ["dashboard", "classes", "attendance", "assessments"]
        }
    
    # Check if user is student
    result = await db.execute(select(Student).where(Student.id == user_id))
    student = result.scalar_one_or_none()
    if student:
        return {
            "user_id": str(user_id),
            "role": "student",
            "tenant_id": str(student.tenant_id), 
            "pages": ["dashboard", "timetable", "assessments", "profile"]
        }
    
    raise HTTPException(status_code=404, detail="User not found")