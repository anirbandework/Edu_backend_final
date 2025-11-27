#!/usr/bin/env python3

import asyncio
from app.core.database import get_db
from sqlalchemy import text

async def check_tables():
    """Check table structures"""
    
    async for db in get_db():
        try:
            # Check tenants table structure
            print("=== TENANTS TABLE ===")
            result = await db.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'tenants'
                ORDER BY ordinal_position
            """))
            
            for row in result.fetchall():
                print(f"{row[0]}: {row[1]}")
            
            # Check if any tenants exist
            print("\n=== EXISTING TENANTS ===")
            result = await db.execute(text("SELECT * FROM tenants LIMIT 3"))
            tenants = result.fetchall()
            
            if tenants:
                for tenant in tenants:
                    print(f"Tenant: {tenant}")
            else:
                print("No tenants found")
            
            # Check topics table
            print("\n=== TOPICS TABLE ===")
            result = await db.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'topics'
                ORDER BY ordinal_position
            """))
            
            for row in result.fetchall():
                print(f"{row[0]}: {row[1]}")
                
        except Exception as e:
            print(f"Error: {e}")
        finally:
            break

if __name__ == "__main__":
    asyncio.run(check_tables())