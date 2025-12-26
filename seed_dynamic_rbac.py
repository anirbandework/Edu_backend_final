#!/usr/bin/env python3
"""
Seeder script for Dynamic RBAC System
This script seeds default page permissions for all existing tenants
"""

import asyncio
import sys
import os
from uuid import uuid4

# Add the app directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.core.database import get_db
from app.services.page_permission_service import PagePermissionService
from app.models.role_management import Role
from app.models.shared.tenant import Tenant
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

async def seed_all_tenants():
    """Seed default permissions for all tenants"""
    print("🌱 Seeding Dynamic RBAC Permissions")
    print("=" * 50)
    
    # Get database session
    async for db in get_db():
        try:
            # Get all active tenants
            print("\n📋 Fetching all active tenants...")
            tenants_result = await db.execute(
                select(Tenant).where(Tenant.is_active == True)
            )
            tenants = tenants_result.scalars().all()
            
            if not tenants:
                print("❌ No active tenants found")
                return
            
            print(f"✅ Found {len(tenants)} active tenants")
            
            # Process each tenant
            for i, tenant in enumerate(tenants, 1):
                print(f"\n🏫 Processing tenant {i}/{len(tenants)}: {tenant.school_name}")
                
                try:
                    # Check if tenant has roles
                    roles_result = await db.execute(
                        select(Role).where(
                            Role.tenant_id == tenant.id,
                            Role.is_active == True
                        )
                    )
                    roles = roles_result.scalars().all()
                    
                    if not roles:
                        print(f"   ⚠️  No roles found for {tenant.school_name}, skipping...")
                        continue
                    
                    print(f"   📝 Found {len(roles)} roles: {', '.join([r.role_name for r in roles])}")
                    
                    # Seed default permissions
                    await PagePermissionService.seed_default_permissions(db, tenant.id)
                    print(f"   ✅ Seeded permissions for {tenant.school_name}")
                    
                except Exception as e:
                    print(f"   ❌ Error seeding {tenant.school_name}: {e}")
                    continue
            
            print(f"\n🎉 Seeding completed for {len(tenants)} tenants!")
            print("=" * 50)
            
        except Exception as e:
            print(f"❌ Error during seeding: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await db.close()
            break

async def create_default_roles_if_missing():
    """Create default roles for tenants that don't have any"""
    print("🔧 Creating default roles for tenants without roles")
    print("=" * 50)
    
    async for db in get_db():
        try:
            # Get all active tenants
            tenants_result = await db.execute(
                select(Tenant).where(Tenant.is_active == True)
            )
            tenants = tenants_result.scalars().all()
            
            for tenant in tenants:
                # Check if tenant has roles
                roles_result = await db.execute(
                    select(Role).where(
                        Role.tenant_id == tenant.id,
                        Role.is_active == True
                    )
                )
                roles = roles_result.scalars().all()
                
                if not roles:
                    print(f"🏫 Creating default roles for {tenant.school_name}")
                    
                    # Create default roles
                    default_roles = [
                        {
                            "role_name": "admin",
                            "subrole": None,
                            "description": "School Administrator with full access"
                        },
                        {
                            "role_name": "teacher",
                            "subrole": None,
                            "description": "Teacher with academic management access"
                        },
                        {
                            "role_name": "student",
                            "subrole": None,
                            "description": "Student with learning access"
                        }
                    ]
                    
                    for role_data in default_roles:
                        role = Role(
                            tenant_id=tenant.id,
                            role_name=role_data["role_name"],
                            subrole=role_data["subrole"],
                            description=role_data["description"],
                            is_active=True
                        )
                        db.add(role)
                    
                    await db.commit()
                    print(f"   ✅ Created 3 default roles for {tenant.school_name}")
            
            print("🎉 Default role creation completed!")
            
        except Exception as e:
            print(f"❌ Error creating default roles: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await db.close()
            break

async def main():
    """Main seeder function"""
    print("🚀 Dynamic RBAC Seeder")
    print("This script will:")
    print("1. Create default roles for tenants without roles")
    print("2. Seed default page permissions for all tenants")
    print()
    
    # Ask for confirmation
    response = input("Do you want to continue? (y/N): ").strip().lower()
    if response != 'y':
        print("❌ Seeding cancelled")
        return
    
    # Step 1: Create default roles
    await create_default_roles_if_missing()
    
    # Step 2: Seed permissions
    await seed_all_tenants()
    
    print("\n🎉 All seeding operations completed!")

if __name__ == "__main__":
    asyncio.run(main())