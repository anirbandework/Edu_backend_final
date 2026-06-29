# app/main.py
from dotenv import load_dotenv
load_dotenv()


from fastapi import FastAPI, Request, HTTPException, Depends
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
from .tenant_management.routers.tenant import router as tenant_router
from .school_authority_management.routers.school_authority import router as school_authority_router
from .student_management.routers.student import router as student_router
from .class_management.routers.class_management import router as class_router
from .enrollment_management.routers.enrollment import router as enrollment_router
from .notification_management.routers.notifications import router as notifications_router
from .attendance_management.routers.attendance import router as attendance_router
from .timetable_management.routers.timetable import router as timetable_router
from .chat_management.routers.chat_router import router as chat_router
from .chat_management.routers.websocket_router import router as websocket_router
from .assessment_management.routers import assessment_router
from .exam_management.routers.exam_management import router as exam_router
from .feedback_management.routers.feedback import router as feedback_router
from .staff_management.routers.staff import router as staff_router
from .auth_rbac.routers.auth import router as auth_router
from .auth_rbac.access.router import router as access_rbac_router
# Eagerly register the SuperAdmin model (only lazily imported in login_service)
# so the startup create_all below also builds the super_admins table.
from .auth_rbac.models.super_admin import SuperAdmin  # noqa: F401
# Eager import so create_all builds members + role_creatable_roles.
from .staff_management.models.member import Member  # noqa: F401
from .auth_rbac.access.models import RoleCreatableRole  # noqa: F401
from .models.base import Base
# NOTE: the legacy page-based access routers (user_role, user_access, role_management,
# page_permissions, rbac_management, super_admin grant-pages) are retired — superseded
# by the module/tab system at /api/access. The frontend used none of them. Their model
# classes are still imported via auth_service, so the Tenant mapper stays intact until
# the Phase-2 cleanup removes the dead models/services/relationships.
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

    # Auto-create any NEW tables from the ORM models on startup (same convenience
    # as the indusinfotechs backend). IMPORTANT: create_all only CREATES missing
    # tables — it does NOT alter existing ones. Column/index/FK changes to existing
    # tables still go through `python -m database_compare.run_local_migration`.
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("ORM tables ensured on startup (create_all)")
    except Exception as e:
        logger.error(f"create_all failed during startup: {e}")

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
    # Always log the full detail server-side...
    logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
    # ...but never leak internals to the client outside local development.
    detail = f"Internal server error: {exc}" if not settings.is_production else "Internal server error"
    return JSONResponse(status_code=500, content={"detail": detail})





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


# CORS configuration — locked to known origins (no wildcard). Configure via
# settings.allowed_origins (env ALLOWED_ORIGINS). Wildcard is rejected in production.
# In development, `flutter run` serves the web app on a dynamic localhost port, so
# we additionally allow any localhost/127.0.0.1 origin via regex (dev only).
_cors_origins = list(settings.allowed_origins)
if settings.is_production and "*" in _cors_origins:
    logger.warning("CORS '*' is not allowed in production; ignoring wildcard.")
    _cors_origins = [o for o in _cors_origins if o != "*"]

_cors_kwargs = dict(
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=3600,
)
if not settings.is_production:
    # any http(s)://localhost:PORT or 127.0.0.1:PORT (Flutter web dev server)
    _cors_kwargs["allow_origin_regex"] = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

app.add_middleware(CORSMiddleware, **_cors_kwargs)


# --- Authorization wiring ---------------------------------------------------
# Every resource router now requires a valid access token (AUTHED). Platform-admin
# routers require super-admin (SUPERADMIN). Public surface is deliberately tiny:
# only health and the auth endpoints (auth_router exposes GET /api/auth/schools as
# the public login-picker list). The tenant router is fully super-admin gated.
from .auth_rbac.security.deps import get_current_principal, require_super_admin
AUTHED = [Depends(get_current_principal)]
SUPERADMIN = [Depends(require_super_admin)]

# Public (no token required)
app.include_router(health_router)
app.include_router(auth_router)

# Platform administration — super-admin only (school CRUD, financials, bulk, hard-delete)
app.include_router(tenant_router, dependencies=SUPERADMIN)

# Authenticated resource routers
app.include_router(school_authority_router, dependencies=AUTHED)
app.include_router(student_router, dependencies=AUTHED)
app.include_router(class_router, dependencies=AUTHED)
app.include_router(enrollment_router, dependencies=AUTHED)
app.include_router(notifications_router, dependencies=AUTHED)
app.include_router(attendance_router, dependencies=AUTHED)
app.include_router(timetable_router, dependencies=AUTHED)
app.include_router(chat_router, dependencies=AUTHED)
app.include_router(websocket_router)  # auth via ?token= JWT handshake (see websocket_router)
app.include_router(assessment_router, dependencies=AUTHED)
app.include_router(exam_router, dependencies=AUTHED)
# Feedback: submit is open to any authed user; listing/triage is super-admin
# (gated per-route inside the router).
app.include_router(feedback_router, dependencies=AUTHED)
app.include_router(staff_router, dependencies=AUTHED)

# Access control — module/tab RBAC (indusinfotechs-style): my-permissions + role
# mgmt + tenant config. Per-route auth inside the router. This is the ONLY
# access-control surface; the legacy page-based routers were retired (see import note).
app.include_router(access_rbac_router)




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
