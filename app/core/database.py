# app/core/database.py
"""Database connection and session management using SQLAlchemy."""
import contextlib
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import text
import logging

from .config import settings

logger = logging.getLogger(__name__)

# Enhanced engine configuration for bulk operations and background tasks
engine = create_async_engine(
    settings.database_url,
    echo=(settings.environment == 'development'),
    connect_args={
        "command_timeout": 300,
        "server_settings": {
            "jit": "off",
            "application_name": "eduassist_api",
            "statement_timeout": "300s",
            "idle_in_transaction_session_timeout": "60s",
            "lock_timeout": "30s",
        }
    }
)

# Separate engine for background tasks
background_engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={
        "command_timeout": 600,
        "server_settings": {
            "jit": "off",
            "application_name": "eduassist_background",
            "statement_timeout": "600s",
            "idle_in_transaction_session_timeout": "120s",
        }
    }
)

# Regular session factory for API requests
AsyncSessionLocal = async_sessionmaker(
    engine, 
    expire_on_commit=False, 
    class_=AsyncSession,
    autoflush=False,  # Manual control over flushing
    autocommit=False,
)

# Background task session factory with separate engine
AsyncBackgroundSessionLocal = async_sessionmaker(
    background_engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False,
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for API requests with proper error handling"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()

# Context manager for background tasks
get_background_db_context = contextlib.asynccontextmanager(
    lambda: AsyncBackgroundSessionLocal()
)

async def get_background_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for background tasks - use with async context manager"""
    async with AsyncBackgroundSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Background database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()

async def health_check_db():
    """Fast health check with timeout handling"""
    try:
        async with engine.connect() as conn:
            # Quick test query with timeout
            result = await conn.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False

async def execute_raw_sql(query: str, params: dict = None, use_background_engine: bool = False):
    """Execute raw SQL with error handling and engine selection"""
    selected_engine = background_engine if use_background_engine else engine
    try:
        async with selected_engine.connect() as conn:
            result = await conn.execute(text(query), params or {})
            await conn.commit()  # Explicit commit for raw SQL
            return result.fetchall()
    except Exception as e:
        logger.error(f"Raw SQL execution failed: {e}")
        raise

async def execute_bulk_raw_sql(query: str, params: dict = None):
    """Execute bulk raw SQL operations using background engine"""
    return await execute_raw_sql(query, params, use_background_engine=True)

# Connection test function for debugging
async def test_connection():
    """Test database connection with detailed error info"""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version(), NOW(), current_database()"))
            row = result.fetchone()
            return {
                "status": "success",
                "version": row[0],
                "timestamp": str(row[1]),
                "database": row[2],
                "pool_status": {
                    "main_pool_size": engine.pool.size(),
                    "main_pool_checked_in": engine.pool.checkedin(),
                    "main_pool_checked_out": engine.pool.checkedout(),
                    "background_pool_size": background_engine.pool.size(),
                    "background_pool_checked_in": background_engine.pool.checkedin(),
                    "background_pool_checked_out": background_engine.pool.checkedout(),
                }
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "type": type(e).__name__
        }

async def get_pool_status():
    """Get detailed connection pool status for monitoring - FIXED"""
    try:
        main_pool = engine.pool
        background_pool = background_engine.pool
        
        return {
            "main_engine": {
                "pool_size": main_pool.size(),
                "checked_in": main_pool.checkedin(),
                "checked_out": main_pool.checkedout(),
                # Removed overflow() and invalidated() - these don't exist on QueuePool
            },
            "background_engine": {
                "pool_size": background_pool.size(),
                "checked_in": background_pool.checkedin(),
                "checked_out": background_pool.checkedout(),
                # Removed overflow() and invalidated() - these don't exist on QueuePool
            }
        }
    except Exception as e:
        logger.error(f"Failed to get pool status: {e}")
        return {"error": str(e)}

# Cleanup function for application shutdown
async def close_db_connections():
    """Properly close all database connections"""
    await engine.dispose()
    await background_engine.dispose()
    logger.info("Database connections closed")
