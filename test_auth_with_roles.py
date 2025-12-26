#!/usr/bin/env python3
"""
Test auth API with users who have roles assigned
"""

import asyncio
import sys
import os

# Add the app directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.core.database import get_db
from app.services.auth_service import AuthService
from app.models.role_management import UserRole, Role
from app.models.tenant_specific.school_authority import SchoolAuthority
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

async def test_auth_with_roles():
    """Test auth API with users who have roles"""
    print("🔍 Testing Auth API with Role-Assigned Users")
    print("=" * 50)
    
    async for db in get_db():
        try:
            # Find users with roles
            user_roles_result = await db.execute(
                select(UserRole)
                .options(selectinload(UserRole.role))
                .limit(5)
            )
            user_roles = user_roles_result.scalars().all()
            
            if not user_roles:
                print("❌ No users with roles found")
                return
            
            print(f"📋 Found {len(user_roles)} users with roles")
            
            for i, user_role in enumerate(user_roles[:2]):  # Test first 2 users
                print(f"\n--- Testing User {i+1} ---")
                print(f"User ID: {user_role.user_id}")
                print(f"User Type: {user_role.user_type}")
                print(f"Role: {user_role.role.role_name}")
                print(f"Tenant ID: {user_role.tenant_id}")
                
                # Get user profile
                profile = await AuthService.get_user_profile(
                    db, user_role.user_id, user_role.tenant_id
                )
                
                if profile:
                    permissions = profile.get('page_permissions', [])
                    print(f"✅ Found {len(permissions)} page permissions")
                    
                    if permissions:
                        # Show first permission details
                        first_perm = permissions[0]
                        print(f"Sample permission - {first_perm['page_name']}:")
                        perms = first_perm['permissions']
                        print(f"  - can_view: {perms['can_view']}")
                        print(f"  - can_create: {perms['can_create']}")
                        print(f"  - can_edit: {perms['can_edit']}")
                        print(f"  - can_delete: {perms['can_delete']}")
                        print(f"  - can_export: {perms['can_export']}")
                        print(f"  - can_import: {perms['can_import']}")
                        
                        # Check if all permissions are True
                        all_true = all(
                            all([
                                perm['permissions']['can_view'],
                                perm['permissions']['can_create'],
                                perm['permissions']['can_edit'],
                                perm['permissions']['can_delete'],
                                perm['permissions']['can_export'],
                                perm['permissions']['can_import']
                            ])
                            for perm in permissions
                        )
                        
                        if all_true:
                            print("  ✅ ALL PERMISSIONS ARE TRUE!")
                        else:
                            print("  ⚠️  Some permissions are not True")
                    else:
                        print("  ℹ️  No permissions found")
                else:
                    print("  ❌ No profile returned")
            
            print("\n🎉 Auth API Role Test Completed!")
            print("=" * 50)
            
        except Exception as e:
            print(f"❌ Error during testing: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await db.close()
            break

if __name__ == "__main__":
    print("Starting Auth API role test...")
    asyncio.run(test_auth_with_roles())