# Dynamic RBAC System Documentation

## Overview

The new Dynamic RBAC (Role-Based Access Control) system provides a flexible, database-driven approach to managing user permissions and page access in the educational platform. Unlike static role definitions, this system allows for dynamic configuration of what pages and actions each role can access.

## Key Features

### 🎯 Dynamic Page Management
- Pages are stored in the database with detailed permission settings
- Each page can have granular permissions (view, create, edit, delete, export, import)
- Custom permissions can be added via JSON fields
- Pages are organized by categories for better management

### 🔐 Role-Based Permissions
- Permissions are assigned per role per tenant
- Different tenants can have different page access for the same role
- Supports inheritance and custom permission overrides

### 🚀 Frontend Integration
- Auth API returns complete page permissions for logged-in users
- Frontend can dynamically build navigation based on user permissions
- Real-time permission checking for UI elements

## Database Schema

### PagePermission Model
```python
class PagePermission(Base):
    __tablename__ = "page_permissions"
    
    # Identifiers
    id = UUID (Primary Key)
    tenant_id = UUID (Foreign Key to tenants)
    role_id = UUID (Foreign Key to roles)
    
    # Page Details
    page_id = String(100)        # Unique identifier
    page_name = String(200)      # Display name
    page_path = String(500)      # Route path
    page_icon = String(100)      # Icon name
    page_category = String(100)  # Category for grouping
    
    # Standard Permissions
    can_view = Boolean
    can_create = Boolean
    can_edit = Boolean
    can_delete = Boolean
    can_export = Boolean
    can_import = Boolean
    
    # Custom Permissions
    custom_permissions = JSONB   # Flexible custom permissions
    
    # Status
    is_active = Boolean
```

## API Endpoints

### Page Permissions Management

#### Create Page Permission
```http
POST /api/page-permissions/role/{role_id}?tenant_id={tenant_id}
```

#### Get Role Permissions
```http
GET /api/page-permissions/role/{role_id}?tenant_id={tenant_id}
```

#### Update Role Permissions
```http
PUT /api/page-permissions/role/{role_id}?tenant_id={tenant_id}
```

#### Seed Default Permissions
```http
POST /api/page-permissions/tenant/{tenant_id}/seed
```

#### Get User Accessible Pages
```http
GET /api/page-permissions/user-pages?tenant_id={tenant_id}&role_id={role_id}
```

### Enhanced Auth API

The auth API now returns page permissions:

```http
GET /api/auth/user-profile/{user_id}?tenant_id={tenant_id}
```

Response includes:
```json
{
  "user_id": "uuid",
  "user_type": "STUDENT|TEACHER|SCHOOL_AUTHORITY",
  "role": "student|teacher|admin",
  "page_permissions": [
    {
      "page_id": "dashboard",
      "page_name": "Dashboard",
      "page_path": "/dashboard",
      "page_icon": "dashboard",
      "page_category": "Main",
      "permissions": {
        "can_view": true,
        "can_create": false,
        "can_edit": false,
        "can_delete": false,
        "can_export": false,
        "can_import": false,
        "custom": {}
      }
    }
  ]
}
```

## Default Page Configuration

### Standard Pages
- **Dashboard**: Main overview page
- **Profile**: User profile management
- **Classes**: Class management and viewing
- **Attendance**: Attendance tracking
- **Timetable**: Schedule viewing
- **Assessments**: Quiz and assessment management
- **Exams**: Exam management and results
- **Chat**: Communication features
- **Notifications**: System notifications
- **AI Tutor**: AI-powered learning assistance

### Admin-Only Pages
- **User Management**: Manage teachers and students
- **Role Management**: Configure roles and permissions
- **System Settings**: Platform configuration

### Default Role Permissions

#### Admin Role
- Full access to all pages
- Can create, edit, delete on most pages
- Access to administrative functions

#### Teacher Role
- View access to most academic pages
- Can create/edit assessments and attendance
- Limited administrative access

#### Student Role
- View-only access to most pages
- Can edit own profile
- Access to learning tools and communication

## Frontend Integration

### Dynamic Navigation
The frontend should use the `page_permissions` from the auth response to build navigation:

```javascript
// Example Flutter/Dart code
List<NavigationItem> buildNavigation(List<PagePermission> permissions) {
  return permissions
    .where((p) => p.permissions.canView)
    .map((p) => NavigationItem(
      id: p.pageId,
      label: p.pageName,
      icon: p.pageIcon,
      path: p.pagePath,
      category: p.pageCategory,
    ))
    .toList();
}
```

### Permission Checking
```javascript
// Check if user can perform action
bool canUserEdit(String pageId, List<PagePermission> permissions) {
  final permission = permissions.firstWhere(
    (p) => p.pageId == pageId,
    orElse: () => null,
  );
  return permission?.permissions.canEdit ?? false;
}
```

## Migration and Setup

### 1. Database Migration
The system requires the `page_permissions` table. Run:
```bash
alembic upgrade head
```

### 2. Seed Default Permissions
For each tenant, seed default permissions:
```bash
curl -X POST "http://localhost:8000/api/page-permissions/tenant/{tenant_id}/seed"
```

### 3. Update Frontend
Update your frontend to:
1. Use the new auth response format
2. Build navigation dynamically
3. Check permissions before showing UI elements

## Service Layer

### PagePermissionService
Main service for managing page permissions:

```python
# Get user's accessible pages
pages = await PagePermissionService.get_user_accessible_pages(
    db, tenant_id, role_id
)

# Update role permissions
await PagePermissionService.update_role_permissions(
    db, tenant_id, role_id, permissions_data
)

# Seed default permissions
await PagePermissionService.seed_default_permissions(
    db, tenant_id
)
```

## Benefits

### 🎯 Flexibility
- Easy to add new pages without code changes
- Granular permission control
- Tenant-specific customization

### 🔒 Security
- Database-driven permissions
- Role-based access control
- Audit trail for permission changes

### 🚀 Scalability
- Efficient database queries
- Caching-friendly design
- Supports large numbers of users and tenants

### 🛠 Maintainability
- Clear separation of concerns
- Easy to test and debug
- Comprehensive API coverage

## Testing

Use the provided test script:
```bash
python test_dynamic_rbac.py
```

This will verify:
- Database connectivity
- Role and tenant queries
- Permission retrieval
- Service functionality

## Future Enhancements

### Planned Features
1. **Permission Inheritance**: Child roles inherit parent permissions
2. **Time-based Permissions**: Temporary access grants
3. **Conditional Permissions**: Context-aware permissions
4. **Permission Templates**: Reusable permission sets
5. **Audit Logging**: Track permission changes
6. **Bulk Operations**: Mass permission updates

### Integration Points
1. **Caching Layer**: Redis-based permission caching
2. **Real-time Updates**: WebSocket permission updates
3. **Analytics**: Permission usage tracking
4. **Mobile Support**: Offline permission sync

## Troubleshooting

### Common Issues

1. **Migration Errors**: Ensure all dependencies are installed
2. **Permission Denied**: Check role assignments
3. **Missing Pages**: Run seed command for tenant
4. **Frontend Issues**: Verify auth response parsing

### Debug Commands
```bash
# Check current migration status
alembic current

# View role permissions
curl "http://localhost:8000/api/page-permissions/role/{role_id}?tenant_id={tenant_id}"

# Test user profile
curl "http://localhost:8000/api/auth/user-profile/{user_id}?tenant_id={tenant_id}"
```

## Conclusion

The Dynamic RBAC system provides a robust, flexible foundation for managing user permissions in the educational platform. It supports the complex requirements of multi-tenant educational environments while maintaining simplicity for developers and administrators.