# app/core/exceptions.py
"""Custom exceptions and error handlers for the EduAssist application."""
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class EduAssistException(HTTPException):
    """Base exception for EduAssist application."""
    def __init__(
        self, 
        status_code: int, 
        detail: str, 
        headers: Optional[Dict[str, Any]] = None
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)


class TenantNotFound(EduAssistException):
    """Exception raised when tenant is not found."""
    def __init__(self):
        super().__init__(
            status_code=404,
            detail="School not found"
        )


class DuplicateTenantError(EduAssistException):
    """Exception raised when duplicate tenant data is found."""
    def __init__(self, field: str, value: str):
        super().__init__(
            status_code=409,
            detail={
                "error": f"Duplicate {field}",
                "message": f"A school with this {field} already exists",
                "field": field,
                "value": value
            }
        )


class BulkOperationError(EduAssistException):
    """Exception raised during bulk operations."""
    def __init__(self, message: str):
        super().__init__(
            status_code=400,
            detail={
                "error": "Bulk Operation Failed",
                "message": message
            }
        )


class ValidationError(EduAssistException):
    """Exception raised for validation errors."""
    def __init__(self, message: str, field: Optional[str] = None):
        detail = {"error": "Validation Error", "message": message}
        if field:
            detail["field"] = field
        super().__init__(status_code=422, detail=detail)


class DatabaseError(EduAssistException):
    """Exception raised for database errors."""
    def __init__(self, message: str):
        super().__init__(
            status_code=500,
            detail={
                "error": "Database Error", 
                "message": message
            }
        )


# Assessment-specific exceptions
class AssessmentException(EduAssistException):
    """Base exception for assessment system"""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(status_code=status_code, detail=message)


class QuizNotFound(EduAssistException):
    """Exception raised when quiz is not found."""
    def __init__(self, quiz_id: str = None):
        message = "Quiz not found"
        if quiz_id:
            message += f" with id: {quiz_id}"
        super().__init__(status_code=404, detail=message)


class QuestionNotFound(EduAssistException):
    """Exception raised when question is not found."""
    def __init__(self, question_id: str = None):
        message = "Question not found"
        if question_id:
            message += f" with id: {question_id}"
        super().__init__(status_code=404, detail=message)


class AIServiceError(EduAssistException):
    """Exception raised for AI service errors."""
    def __init__(self, message: str):
        super().__init__(
            status_code=503,
            detail={
                "error": "AI Service Error",
                "message": message
            }
        )


# FastAPI Error Handlers
async def eduassist_exception_handler(request: Request, exc: EduAssistException):
    """Handle custom EduAssist exceptions"""
    logger.error(f"EduAssist error: {exc.detail} - Path: {request.url.path}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "type": exc.__class__.__name__}
    )


async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions"""
    logger.error(f"Unexpected error: {str(exc)} - Path: {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "type": "InternalError"}
    )
