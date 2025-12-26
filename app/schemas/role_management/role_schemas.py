from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from enum import Enum

class UserType(str, Enum):
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"
    SCHOOL_AUTHORITY = "SCHOOL_AUTHORITY"

class RoleCreate(BaseModel):
    role_name: str = Field(..., max_length=50)
    subrole: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=255)

class RoleResponse(BaseModel):
    id: UUID
    role_name: str
    subrole: Optional[str]
    description: Optional[str]
    is_active: bool
    tenant_id: UUID

class UserRoleAssign(BaseModel):
    user_id: UUID
    user_type: UserType
    role_id: UUID

class UserRoleResponse(BaseModel):
    id: UUID
    user_id: UUID
    user_type: UserType
    role: RoleResponse
    tenant_id: UUID

class UserWithRoles(BaseModel):
    user_id: UUID
    user_type: UserType
    roles: List[RoleResponse]