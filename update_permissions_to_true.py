#!/usr/bin/env python3
"""
Update all existing page permissions to True
This script sets all permission flags to True for all existing page permissions
"""

import asyncio
import sys
import os

# Add the app directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.core.database import get_db
from app.models.role_management import PagePermission
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

async def update_all_permissions_to_true():
    """Update all existing page permissions to True"""
    print("🔧 Updating All Page Permissions to True")
    print("=" * 50)
    
    async for db in get_db():
        try:
            # Get count of existing permissions
            count_result = await db.execute(
                select(PagePermission).where(PagePermission.is_active == True)
            )
            permissions = count_result.scalars().all()
            total_count = len(permissions)
            
            print(f"📋 Found {total_count} existing page permissions")
            
            if total_count == 0:
                print("ℹ️  No permissions found to update")
                return
            
            # Update all permissions to True
            await db.execute(
                update(PagePermission)
                .where(PagePermission.is_active == True)
                .values(
                    can_view=True,
                    can_create=True,
                    can_edit=True,
                    can_delete=True,
                    can_export=True,
                    can_import=True
                )
            )
            
            await db.commit()
            
            print(f"✅ Successfully updated {total_count} permissions")
            print("   All permissions now set to:")
            print("   - can_view: True")
            print("   - can_create: True") 
            print("   - can_edit: True")
            print("   - can_delete: True")
            print("   - can_export: True")
            print("   - can_import: True")
            
            print("\n🎉 All permissions updated successfully!")
            print("=" * 50)
            
        except Exception as e:
            print(f"❌ Error updating permissions: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await db.close()
            break

if __name__ == "__main__":
    print("Starting permission update...")
    asyncio.run(update_all_permissions_to_true())