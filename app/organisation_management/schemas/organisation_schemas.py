# app/schemas/organisation_schemas.py
"""Pydantic schemas for Organisation (Organisation) entity."""
from typing import List, Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

class OrganisationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Organisation name")
    address: str = Field(..., min_length=1, max_length=500, description="Organisation address")
    phone: str = Field(..., min_length=10, max_length=20, description="Phone number")
    email: EmailStr = Field(..., description="Email address")
    head_name: str = Field(..., min_length=1, max_length=100, description="Head name")
    is_active: Optional[bool] = Field(default=True, description="Active status")

    # amazonq-ignore-next-line
    annual_tuition: Optional[float] = Field(default=0, ge=0, description="Annual fee")
    registration_fee: Optional[float] = Field(default=0, ge=0, description="Registration fee")
    charges_applied: Optional[bool] = Field(default=False, description="Whether additional charges are applied")
    charges_amount: Optional[float] = Field(default=None, ge=0, description="Additional charges amount")

    maximum_capacity: Optional[int] = Field(default=None, gt=0, description="Maximum capacity")

    org_type: Optional[str] = Field(default="School", max_length=20, description="Organisation type")
    levels_offered: Optional[List[str]] = Field(default=None, description="Levels / programs offered")
    established_year: Optional[int] = Field(default=None, ge=1800, le=datetime.now().year + 1, description="Established year")
    accreditation: Optional[str] = Field(default=None, max_length=50, description="Accreditation")
    language_of_instruction: Optional[str] = Field(default="English", max_length=20, description="Language of instruction")
    
    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        try:
            if not v or not isinstance(v, str):
                raise ValueError('Phone number must be a non-empty string')
            cleaned = ''.join(c for c in v if c.isdigit())
            if not cleaned.isdigit():
                raise ValueError('Phone number must contain only digits and valid separators')
            return v
        # amazonq-ignore-next-line
        except AttributeError:
            raise ValueError('Phone number must be a valid string')
    
    @model_validator(mode='after')
    def validate_charges(self):
        if self.charges_applied and self.charges_amount is None:
            raise ValueError('charges_amount is required when charges_applied is True')
        return self
    


class OrganisationCreate(OrganisationBase):
    """Schema for creating a new organisation"""
    pass  # code not needed for creation

class OrganisationUpdate(BaseModel):
    """Schema for updating organisation - all fields optional"""
    # amazonq-ignore-next-line
    code: Optional[str] = Field(default=None, max_length=10)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    address: Optional[str] = Field(default=None, min_length=1, max_length=500)
    # amazonq-ignore-next-line
    phone: Optional[str] = Field(default=None, min_length=10, max_length=20)
    email: Optional[EmailStr] = Field(default=None)
    head_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    is_active: Optional[bool] = Field(default=None)
    annual_tuition: Optional[float] = Field(default=None, ge=0)
    registration_fee: Optional[float] = Field(default=None, ge=0)
    charges_applied: Optional[bool] = Field(default=None)
    charges_amount: Optional[float] = Field(default=None, ge=0)
    # amazonq-ignore-next-line
    maximum_capacity: Optional[int] = Field(default=None, gt=0)
    org_type: Optional[str] = Field(default=None, max_length=20)
    levels_offered: Optional[List[str]] = Field(default=None)
    established_year: Optional[int] = Field(default=None, ge=1800, le=datetime.now().year + 1)
    accreditation: Optional[str] = Field(default=None, max_length=50)
    language_of_instruction: Optional[str] = Field(default=None, max_length=20)
    


class OrganisationInDBBase(OrganisationBase):
    code: str = Field(..., description="Auto-generated organisation code")
    id: UUID = Field(..., description="Unique identifier")
    owner_authority_id: Optional[UUID] = Field(default=None, description="Admin who owns this organisation")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        from_attributes = True

class Organisation(OrganisationInDBBase):
    """Complete organisation schema for API responses"""
    pass
