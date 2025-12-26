from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from ..core.database import get_db
from ..models.tenant_specific.school_authority import SchoolAuthority
from ..models.tenant_specific.teacher import Teacher
from ..models.tenant_specific.student import Student

router = APIRouter(prefix="/api/v1/user", tags=["User Role"])

@router.get("/{user_id}/role")
async def get_user_role(user_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get user role by UUID"""
    
    # Check if user is school authority
    result = await db.execute(select(SchoolAuthority).where(SchoolAuthority.id == user_id))
    if result.scalar_one_or_none():
        return {"role": "admin"}
    
    # Check if user is teacher
    result = await db.execute(select(Teacher).where(Teacher.id == user_id))
    if result.scalar_one_or_none():
        return {"role": "teacher"}
    
    # Check if user is student
    result = await db.execute(select(Student).where(Student.id == user_id))
    if result.scalar_one_or_none():
        return {"role": "student"}
    
    raise HTTPException(status_code=404, detail="User not found")