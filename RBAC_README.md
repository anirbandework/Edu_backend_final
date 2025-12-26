# EduAssist RBAC System

A comprehensive Role-Based Access Control (RBAC) system for the EduAssist educational management platform.

## Features

- **Multi-tenant Support**: Tenant-isolated roles, pages, and permissions
- **Caching**: Redis-based caching for performance optimization
- **Bulk Operations**: Efficient bulk permission updates
- **Default Data Seeding**: Pre-configured roles and permissions
- **JWT Integration**: Token-based authentication and authorization
- **Audit Trail**: Track all permission changes
- **RESTful API**: Complete CRUD operations for all RBAC entities

## Database Models

### Role Model
- `key`: Unique role identifier (e.g., 'admin', 'teacher', 'student')
- `label`: Human-readable role name
- `description`: Role description
- `color`: Hex color for UI representation
- `is_active`: Role status
- `tenant_id`: Multi-tenant support

### Page Model
- `key`: Unique page identifier (e.g., 'dashboard', 'student-management')
- `label`: Human-readable page name
- `category`: Page grouping (e.g., 'User Management', 'Academic Management')
- `description`: Page description
- `icon`: Icon code for UI
- `is_active`: Page status
- `tenant_id`: Multi-tenant support

### Permission Model
- `role_id`: Foreign key to Role
- `page_id`: Foreign key to Page
- `has_access`: Boolean access flag
- `tenant_id`: Multi-tenant support

## API Endpoints

### Role Management
```
GET    /api/v1/rbac/roles/           # List all roles
POST   /api/v1/rbac/roles/           # Create new role
GET    /api/v1/rbac/roles/{key}/     # Get specific role
PUT    /api/v1/rbac/roles/{key}/     # Update role
DELETE /api/v1/rbac/roles/{key}/     # Delete role
```

### Page Management
```
GET    /api/v1/rbac/pages/           # List all pages
POST   /api/v1/rbac/pages/           # Create new page
GET    /api/v1/rbac/pages/{key}/     # Get specific page
PUT    /api/v1/rbac/pages/{key}/     # Update page
DELETE /api/v1/rbac/pages/{key}/     # Delete page
```

### Permission Management
```
GET    /api/v1/rbac/permissions/                    # Get permission matrix
POST   /api/v1/rbac/permissions/bulk/               # Bulk update permissions
GET    /api/v1/rbac/permissions/user-permissions/   # Get user permissions for role
```

## Default Roles

- **Administrator** (`admin`): Full system access
- **Teacher** (`teacher`): Academic and class management access
- **Student** (`student`): Limited access to learning resources

## Default Pages by Category

### Dashboard
- Dashboard

### User Management
- Student Management
- Teacher Management
- Admin Management

### Academic Management
- Class Management
- Exam Management
- Attendance Management
- Timetable Management

### Communication
- Chat
- Notifications

### Assessment
- Assessments
- AI Quiz

### System Administration
- Access Control (RBAC)

## Setup Instructions

### 1. Run Database Migration
```bash
alembic upgrade head
```

### 2. Seed Default Data
```bash
# Seed global data
python seed_rbac.py

# Seed for specific tenant
python seed_rbac.py --tenant-id "your-tenant-uuid"
```

### 3. Test the System
```bash
python test_rbac.py
```

## Usage Examples

### Creating a Role
```python
from app.services.rbac_service import RBACService
from app.schemas.rbac import RoleCreate

role_data = RoleCreate(
    key="custom_role",
    label="Custom Role",
    description="Custom role for specific users",
    color="#ff5722"
)

role = await RBACService.create_role(db, role_data, tenant_id)
```

### Checking Permissions
```python
from app.core.rbac_middleware import require_permission

@require_permission("student-management")
async def manage_students():
    # This endpoint requires student-management permission
    pass
```

### Bulk Permission Update
```python
from app.schemas.rbac import BulkPermissionUpdate

updates = BulkPermissionUpdate(
    permissions=[
        {"role_key": "teacher", "page_key": "dashboard", "has_access": True},
        {"role_key": "teacher", "page_key": "student-management", "has_access": False}
    ]
)

await RBACService.bulk_update_permissions(db, updates, tenant_id)
```

## Performance Optimizations

- **Database Indexing**: Optimized indexes on foreign keys and lookup fields
- **Query Optimization**: Uses `select_related` and `prefetch_related` for efficient queries
- **Redis Caching**: Caches permission matrices and user permissions (5-minute TTL)
- **Bulk Operations**: Efficient bulk permission updates

## Security Features

- **JWT Authentication**: Token-based authentication
- **Tenant Isolation**: Complete data isolation between tenants
- **Input Validation**: Comprehensive validation using Pydantic schemas
- **Permission Middleware**: Automatic permission checking for protected endpoints

## Monitoring and Logging

- All permission changes are logged
- Cache hit/miss metrics available
- Database query performance monitoring
- API endpoint response time tracking

## Configuration

The RBAC system uses the following configuration:

```python
# Cache TTL for permissions (seconds)
PERMISSION_CACHE_TTL = 300

# JWT secret key for token verification
JWT_SECRET_KEY = "your-secret-key"

# Database connection settings
DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/db"
```

## Troubleshooting

### Common Issues

1. **Permission Denied Errors**
   - Verify user role in JWT token
   - Check if role has required page permission
   - Ensure tenant isolation is correct

2. **Cache Issues**
   - Clear Redis cache: `await cache_service.delete_pattern("permissions:*")`
   - Check Redis connection

3. **Database Issues**
   - Verify foreign key relationships
   - Check unique constraints on role/page keys per tenant

### Debug Commands

```bash
# Check role permissions
curl "http://localhost:8000/api/v1/rbac/permissions/user-permissions/?role=admin"

# View permission matrix
curl "http://localhost:8000/api/v1/rbac/permissions/"

# List all roles
curl "http://localhost:8000/api/v1/rbac/roles/"
```