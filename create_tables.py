#!/usr/bin/env python3
"""Create all database tables from models"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import engine
from app.models.base import Base

async def create_tables():
    """Create all tables"""
    print("Creating all database tables...")
    
    async with engine.begin() as conn:
        # Drop all tables first (clean slate)
        await conn.run_sync(Base.metadata.drop_all)
        print("Dropped existing tables")
        
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
        print("Created all tables successfully")
    
    await engine.dispose()
    print("Database connection closed")

if __name__ == "__main__":
    asyncio.run(create_tables())