#!/usr/bin/env python3
"""
Test script for Dynamic RBAC System
This script demonstrates the new dynamic RBAC functionality
"""

import asyncio
import sys
import os
from uuid import uuid4

# Add the app directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.core.database import get_db
from app.services.page_permission_service import PagePermissionService
from app.models.role_management import Role, PagePermission
from app.models.shared.tenant import Tenant
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

async def test_dynamic_rbac():
    """Test the dynamic RBAC system"""
    print("🚀 Testing Dynamic RBAC System")
    print("=" * 50)
    
    # Get database session
    async for db in get_db():
        try:
            # Test 1: Check if we can query existing tenants
            print("\n📋 Test 1: Checking existing tenants...")
            tenants_result = await db.execute(select(Tenant).limit(5))
            tenants = tenants_result.scalars().all()
            
            if tenants:
                print(f"✅ Found {len(tenants)} tenants")
                for tenant in tenants:
                    print(f"   - {tenant.school_name} (ID: {tenant.id})")
            else:
                print("❌ No tenants found")
                return
            
            # Test 2: Check if we can query existing roles
            print("\n📋 Test 2: Checking existing roles...")
            roles_result = await db.execute(select(Role).limit(10))
            roles = roles_result.scalars().all()
            
            if roles:
                print(f"✅ Found {len(roles)} roles")
                for role in roles:
                    print(f"   - {role.role_name} ({role.subrole or 'No subrole'}) - Tenant: {role.tenant_id}")
            else:
                print("❌ No roles found")
                return
            
            # Test 3: Test page permissions for a role
            print("\n📋 Test 3: Testing page permissions...")
            test_tenant = tenants[0]
            test_role = None
            
            # Find a role for this tenant
            for role in roles:
                if role.tenant_id == test_tenant.id:
                    test_role = role
                    break
            
            if test_role:
                print(f"✅ Testing with role: {test_role.role_name} for tenant: {test_tenant.school_name}")
                
                # Get existing permissions
                permissions = await PagePermissionService.get_role_permissions(
                    db, test_tenant.id, test_role.id
                )
                
                if permissions:
                    print(f"✅ Found {len(permissions)} existing permissions")
                    for perm in permissions[:3]:  # Show first 3
                        print(f"   - {perm.page_name}: view={perm.can_view}, edit={perm.can_edit}")
                else:
                    print("ℹ️  No existing permissions found")
                
                # Test getting user accessible pages
                accessible_pages = await PagePermissionService.get_user_accessible_pages(
                    db, test_tenant.id, test_role.id
                )
                
                print(f"✅ User can access {len(accessible_pages)} pages")
                for page in accessible_pages[:3]:  # Show first 3
                    print(f"   - {page['page_name']} ({page['page_category']})")
                    
            else:
                print("❌ No role found for the test tenant")
            
            print("\n🎉 Dynamic RBAC System Test Completed!")
            print("=" * 50)
            
        except Exception as e:
            print(f"❌ Error during testing: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await db.close()
            break

if __name__ == "__main__":
    print("Starting Dynamic RBAC Test...")
    asyncio.run(test_dynamic_rbac())