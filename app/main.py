# app/main.py
from dotenv import load_dotenv
load_dotenv()


from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import time
from sqlalchemy import text  # ADDED MISSING IMPORT



from .core.config import settings
from .core.database import engine, background_engine, close_db_connections, get_pool_status
from .core.cache import cache_service
from .routers.health import router as health_router
from .routers.tenant import router as tenant_router
from .routers.school_authority import router as school_authority_router
from .routers.school_authority_management.teacher import router as teacher_router
from .routers.school_authority_management.student import router as student_router
from .routers.school_authority_management.class_management import router as class_router
from .routers.school_authority_management.enrollment import router as enrollment_router
from .routers.school_authority_management.notifications import router as notifications_router
from .routers.school_authority_management.attendance import router as attendance_router
from .routers.school_authority_management.timetable import router as timetable_router
from .routers.chat.chat_router import router as chat_router
from .routers.chat.websocket_router import router as websocket_router
from .routers.school_authority_management.assesment import assessment_router
from .routers.school_authority_management.exam_management import router as exam_router
from .routers.user_role import router as user_role_router
from .routers.auth import router as auth_router
from .routers.role_management.role_router import router as role_management_router
from .routers.page_permissions import router as page_permissions_router
from .routers.rbac_management import router as rbac_management_router
from .core.exceptions import eduassist_exception_handler, general_exception_handler, EduAssistException


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Enhanced application lifespan with bulk operations support"""
    logger.info("Starting EduAssist Backend API")
    
    # Initialize cache manager
    try:
        await cache_service.initialize()
        logger.info("Cache manager initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize cache: {e}")
        # Don't fail startup if cache is unavailable
    
    # Test database connections for both engines
    try:
        # Test main engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Main database engine connected successfully")
        
        # Test background engine
        async with background_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Background database engine connected successfully")
        
        # Log initial pool status
        pool_status = await get_pool_status()
        logger.info(f"Database pool status: {pool_status}")
        
    except Exception as e:
        logger.error(f"Database connection failed during startup: {e}")
        # In production, you might want to fail here
    
    logger.info("Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down EduAssist Backend API")
    
    try:
        await cache_service.close()
        logger.info("Cache manager closed")
    except Exception as e:
        logger.error(f"Error closing cache manager: {e}")
    
    try:
        await close_db_connections()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")
    
    logger.info("Application shutdown complete")


# Create FastAPI app with enhanced lifespan
app = FastAPI(
    title="EduAssist Backend API",
    description="Educational Management Platform API with Bulk Operations Support",
    version=settings.app_version,
    lifespan=lifespan,
    servers=[{"url": "http://localhost:8000"}]
)

# Global exception handler to preserve HTTP status codes
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Ensure HTTPException status codes are preserved"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

# EduAssist system exception handlers
@app.exception_handler(EduAssistException)
async def handle_eduassist_exception(request: Request, exc: EduAssistException):
    return await eduassist_exception_handler(request, exc)

# Global exception handler for all other exceptions
@app.exception_handler(Exception)
async def handle_general_exception(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)}"}
    )





@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Enhanced middleware with pool monitoring for bulk operations - FIXED"""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    response.headers["X-Process-Time"] = str(process_time)
    
    # Add pool status for monitoring (optional, can be disabled in production) - FIXED
    if settings.environment == 'development':
        try:
            pool_status = await get_pool_status()
            # Check if pool_status contains error or proper structure
            if isinstance(pool_status, dict) and "error" not in pool_status:
                if "main_engine" in pool_status and "background_engine" in pool_status:
                    response.headers["X-Main-Pool-Active"] = str(pool_status["main_engine"]["checked_out"])
                    response.headers["X-Background-Pool-Active"] = str(pool_status["background_engine"]["checked_out"])
        except Exception as e:
            # Don't crash the request if pool status fails
            logger.debug(f"Failed to add pool status headers: {e}")
    
    # Log slow requests (especially important for bulk operations)
    if process_time > 5.0:  # Log requests taking longer than 5 seconds
        logger.warning(
            f"Slow request: {request.method} {request.url.path} - {process_time:.3f}s"
        )
    else:
        logger.info(f"{request.method} {request.url.path} - {process_time:.3f}s")
    
    return response


# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001", 
        "http://localhost:8080",
        "http://localhost:53657",
        "http://127.0.0.1:53657",
        "http://192.168.1.10:8000",
        "http://192.168.1.10:3000",
        "*"
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    max_age=3600,
)


# Include routers
app.include_router(health_router)
app.include_router(tenant_router)
app.include_router(school_authority_router)
app.include_router(teacher_router)
app.include_router(student_router)
app.include_router(class_router)
app.include_router(enrollment_router)
app.include_router(notifications_router)
app.include_router(attendance_router)
app.include_router(timetable_router)
app.include_router(chat_router)
app.include_router(websocket_router)
app.include_router(assessment_router)
app.include_router(exam_router)
app.include_router(auth_router)
app.include_router(user_role_router)
app.include_router(role_management_router)
app.include_router(page_permissions_router)
app.include_router(rbac_management_router)




# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "EduAssist Backend API",
        "version": settings.app_version,
        "features": [
            "Tenant Management",
            "School Authority Management",
            "Assessment System",
            "AI-Powered Learning Analytics",
            "Connection Pooling",
            "Bulk Operations",
            "Background Processing",
            "Real-time Chat System",
        ]
    }


# Health check with pool status
@app.get("/system/status")
async def system_status():
    """Enhanced system status including pool information - FIXED"""
    try:
        pool_status = await get_pool_status()
    except Exception as e:
        logger.error(f"Failed to get pool status for system status: {e}")
        pool_status = {"error": str(e)}
    
    return {
        "api_status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
        "database_pools": pool_status,
        "features": {
            "tenant_management": True,
            "school_authority_management": True,
            "assessment_system": True,
            "ai_learning_analytics": True,
            "quiz_management": True,
            "cbse_content": True,
            "grading_system": True,
            "bulk_operations": True,
            "background_tasks": True,
            "connection_pooling": True,
            "cache_manager": True
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",  # Use string import for better reloading
        host="0.0.0.0",
        port=8000,
        reload=(settings.environment == 'development'),
        log_level="info",
        access_log=True
    )
