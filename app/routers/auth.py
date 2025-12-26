from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from ..core.database import get_db
from ..services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

@router.get("/user-profile/{user_id}")
async def get_user_profile(
    user_id: UUID,
    tenant_id: UUID = None,
    db: AsyncSession = Depends(get_db)
):
    """Get complete user profile with roles for login"""
    profile = await AuthService.get_user_profile(db, user_id, tenant_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found or not associated with this tenant")
    return profile