#!/usr/bin/env python3

import asyncio
from sqlalchemy import text
from app.core.database import get_db

async def fix_questions_table():
    """Add missing columns to questions table"""
    
    async for db in get_db():
        try:
            # Check if columns exist
            check_columns_sql = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'questions' 
                AND column_name IN ('version', 'original_source', 'import_batch_id')
            """)
            
            result = await db.execute(check_columns_sql)
            existing_columns = [row[0] for row in result.fetchall()]
            
            print(f"Existing columns: {existing_columns}")
            
            # Add missing columns
            if 'version' not in existing_columns:
                print("Adding version column...")
                await db.execute(text("ALTER TABLE questions ADD COLUMN version INTEGER DEFAULT 1"))
            
            if 'original_source' not in existing_columns:
                print("Adding original_source column...")
                await db.execute(text("ALTER TABLE questions ADD COLUMN original_source VARCHAR(100)"))
            
            if 'import_batch_id' not in existing_columns:
                print("Adding import_batch_id column...")
                await db.execute(text("ALTER TABLE questions ADD COLUMN import_batch_id UUID"))
            
            await db.commit()
            print("Questions table updated successfully!")
            
        except Exception as e:
            print(f"Error: {e}")
            await db.rollback()
        finally:
            break

if __name__ == "__main__":
    asyncio.run(fix_questions_table())