# app/schemas/exam_schemas.py
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum





class ExamCreate(BaseModel):
    exam_name: str = Field(..., max_length=200)
    exam_code: str = Field(..., max_length=50)
    exam_type: str = Field(..., max_length=50)
    description: Optional[str] = None
    academic_year: str = Field(..., max_length=10)
    term: Optional[str] = Field(None, max_length=20)
    subject: Optional[str] = Field(None, max_length=100)
    grade_levels: Optional[List[int]] = None
    exam_date: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    exam_config: Optional[Dict[str, Any]] = None
    marking_scheme: Optional[Dict[str, Any]] = None
    grading_criteria: Optional[Dict[str, Any]] = None
    class_ids: List[str] = Field(..., min_items=1)

class ExamUpdate(BaseModel):
    exam_name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    exam_date: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    exam_config: Optional[Dict[str, Any]] = None
    marking_scheme: Optional[Dict[str, Any]] = None
    grading_criteria: Optional[Dict[str, Any]] = None
    status: Optional[str] = None

class ExamResponse(BaseModel):
    id: str
    exam_name: str
    exam_code: str
    exam_type: str
    description: Optional[str]
    academic_year: str
    term: Optional[str]
    subject: Optional[str]
    grade_levels: Optional[List[int]]
    exam_date: Optional[datetime]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    duration_minutes: Optional[int]
    exam_config: Optional[Dict[str, Any]]
    marking_scheme: Optional[Dict[str, Any]]
    grading_criteria: Optional[Dict[str, Any]]
    status: str
    is_published: bool
    total_students: int
    completed_markings: int
    created_at: datetime

    @validator('id', pre=True)
    def convert_uuid_to_str(cls, v):
        return str(v) if v else None

    class Config:
        from_attributes = True

class StudentMarkCreate(BaseModel):
    student_id: str
    marks_data: Dict[str, Any] = Field(..., description="Flexible marking data")
    total_marks: Optional[int] = None
    obtained_marks: Optional[int] = None
    percentage: Optional[int] = Field(None, ge=0, le=100)
    grade: Optional[str] = Field(None, max_length=5)
    remarks: Optional[str] = None
    attendance_status: Optional[str] = Field("present", max_length=20)

class StudentMarkUpdate(BaseModel):
    marks_data: Optional[Dict[str, Any]] = None
    total_marks: Optional[int] = None
    obtained_marks: Optional[int] = None
    percentage: Optional[int] = Field(None, ge=0, le=100)
    grade: Optional[str] = Field(None, max_length=5)
    remarks: Optional[str] = None
    attendance_status: Optional[str] = Field(None, max_length=20)
    marking_status: Optional[str] = None

class StudentMarkResponse(BaseModel):
    id: str
    exam_id: str
    student_id: str
    class_id: str
    marks_data: Dict[str, Any]
    total_marks: Optional[int]
    obtained_marks: Optional[int]
    percentage: Optional[int]
    grade: Optional[str]
    marking_status: str
    marked_by: Optional[str]
    marked_at: Optional[datetime]
    verified_by: Optional[str]
    verified_at: Optional[datetime]
    remarks: Optional[str]
    attendance_status: str
    created_at: datetime

    @validator('id', 'exam_id', 'student_id', 'class_id', 'marked_by', 'verified_by', pre=True)
    def convert_uuid_to_str(cls, v):
        return str(v) if v else None

    class Config:
        from_attributes = True

class BulkMarkingRequest(BaseModel):
    exam_id: str
    marks_data: List[StudentMarkCreate] = Field(..., min_items=1)
    batch_name: Optional[str] = None

class BulkMarkingResponse(BaseModel):
    batch_id: str
    total_records: int
    success_count: int
    error_count: int
    errors: Optional[List[Dict[str, Any]]] = None

class StudentExamHistory(BaseModel):
    student_id: str
    student_name: str
    exams: List[Dict[str, Any]]
    
class ExamAnalytics(BaseModel):
    exam_id: str
    exam_name: str
    total_students: int
    appeared_students: int
    average_marks: float
    highest_marks: int
    lowest_marks: int
    pass_percentage: float
    grade_distribution: Dict[str, int]