#!/usr/bin/env python3
"""
Test auth API to verify all permissions are True
"""

import asyncio
import sys
import os
import json

# Add the app directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.core.database import get_db
from app.services.auth_service import AuthService
from app.models.tenant_specific.school_authority import SchoolAuthority
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

async def test_auth_api():
    """Test the auth API response"""
    print("🔍 Testing Auth API Response")
    print("=" * 50)
    
    async for db in get_db():
        try:
            # Get a school authority user
            auth_result = await db.execute(select(SchoolAuthority).limit(1))
            auth_user = auth_result.scalar_one_or_none()
            
            if not auth_user:
                print("❌ No school authority user found")
                return
            
            print(f"📋 Testing with user: {auth_user.first_name} {auth_user.last_name}")
            print(f"   User ID: {auth_user.id}")
            print(f"   Tenant ID: {auth_user.tenant_id}")
            
            # Get user profile using auth service
            profile = await AuthService.get_user_profile(db, auth_user.id, auth_user.tenant_id)
            
            if profile:
                print(f"\n✅ Auth API Response:")
                print(f"   User Type: {profile['user_type']}")
                print(f"   Role: {profile['role']}")
                print(f"   Page Permissions Count: {len(profile.get('page_permissions', []))}")
                
                # Show first few permissions to verify they're all True
                permissions = profile.get('page_permissions', [])
                if permissions:
                    print(f"\n📋 Sample Permissions (showing first 3):")
                    for i, perm in enumerate(permissions[:3]):
                        print(f"   {i+1}. {perm['page_name']} ({perm['page_category']}):")
                        perms = perm['permissions']
                        print(f"      - can_view: {perms['can_view']}")
                        print(f"      - can_create: {perms['can_create']}")
                        print(f"      - can_edit: {perms['can_edit']}")
                        print(f"      - can_delete: {perms['can_delete']}")
                        print(f"      - can_export: {perms['can_export']}")
                        print(f"      - can_import: {perms['can_import']}")
                        print()
                
                # Verify all permissions are True
                all_true = True
                for perm in permissions:
                    perms = perm['permissions']
                    if not all([
                        perms['can_view'],
                        perms['can_create'], 
                        perms['can_edit'],
                        perms['can_delete'],
                        perms['can_export'],
                        perms['can_import']
                    ]):
                        all_true = False
                        break
                
                if all_true:
                    print("✅ ALL PERMISSIONS ARE SET TO TRUE!")
                else:
                    print("⚠️  Some permissions are not True")
                    
            else:
                print("❌ No profile returned from auth service")
            
            print("\n🎉 Auth API Test Completed!")
            print("=" * 50)
            
        except Exception as e:
            print(f"❌ Error during testing: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await db.close()
            break

if __name__ == "__main__":
    print("Starting Auth API test...")
    asyncio.run(test_auth_api())