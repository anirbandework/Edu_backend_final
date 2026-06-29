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


# (The specific subclasses — OrganisationNotFound / Duplicate / Quiz / Assessment /
# AIServiceError / etc. — were removed as dead code: every error site raises
# HTTPException(...) directly. Re-add a subclass here only if you actually raise it.)


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
