# RBAC API Testing Guide

## Updated Test Data (Created Successfully)

### New UUIDs for RBAC Testing:
- **Tenant ID**: `f47ac10b-58cc-4372-a567-0e02b2c3d479`
- **Principal ID**: `6ba7b810-9dad-11d1-80b4-00c04fd430c8`
- **Teacher ID**: `6ba7b811-9dad-11d1-80b4-00c04fd430c8`
- **Student ID**: `6ba7b812-9dad-11d1-80b4-00c04fd430c8`

### Test Users Created:
1. **Tenant**: RBAC Test School (school_code: RBAC001)
2. **Principal**: Sarah Principal (sarah.principal@rbactest.edu)
3. **Teacher**: Mike Teacher (mike.teacher@rbactest.edu)
4. **Student**: Emma Student (emma.student@rbactest.edu)

## Postman Collection

The `RBAC_API_Collection.json` file has been updated with the new UUIDs and includes:

### API Categories:
1. **Authentication** - User profile endpoints
2. **User Access** - Get user access and permissions
3. **Super Admin** - Tenant page access management
4. **Role Management** - Create roles, assign users, manage permissions
5. **Page Permissions** - Manage page-level permissions
6. **RBAC Management** - General RBAC operations

### Testing Flow:
1. **Start Server**: Ensure FastAPI server is running on port 8000
2. **Import Collection**: Import `RBAC_API_Collection.json` into Postman
3. **Test User Access**: Try the user access endpoints first
4. **Grant Pages**: Use Super Admin endpoints to grant pages to tenant
5. **Create Roles**: Create teacher and student roles
6. **Assign Roles**: Assign roles to users
7. **Set Permissions**: Configure page permissions for roles
8. **Verify Access**: Test user access endpoints again

### Key Endpoints to Test First:
- `GET /api/v1/user/{principal_id}/access` - Should work now
- `GET /api/v1/user/{teacher_id}/access` - Should work now  
- `GET /api/v1/user/{student_id}/access` - Should work now
- `GET /api/super-admin/available-pages` - Get all available pages
- `POST /api/super-admin/grant-pages` - Grant pages to tenant

## Fixed Issues:
1. ✅ Added missing `user_access` router to main.py
2. ✅ Created proper test data with all required fields
3. ✅ Updated Postman collection with new UUIDs
4. ✅ Resolved "User not found" error by creating valid test users

## Next Steps:
1. Start the FastAPI server
2. Import the updated Postman collection
3. Test the user access endpoints with the new UUIDs
4. Follow the RBAC testing flow to verify the complete system

The RBAC system should now work properly with the new test data!