# Flutter Integration Guide for Dynamic RBAC

## Overview
This guide shows how to integrate the new Dynamic RBAC system with your Flutter frontend.

## 1. Update Auth Response Model

Create or update your auth response model to handle page permissions:

```dart
// lib/models/auth_response.dart
class PagePermission {
  final String pageId;
  final String pageName;
  final String pagePath;
  final String? pageIcon;
  final String? pageCategory;
  final PermissionSet permissions;

  PagePermission({
    required this.pageId,
    required this.pageName,
    required this.pagePath,
    this.pageIcon,
    this.pageCategory,
    required this.permissions,
  });

  factory PagePermission.fromJson(Map<String, dynamic> json) {
    return PagePermission(
      pageId: json['page_id'],
      pageName: json['page_name'],
      pagePath: json['page_path'],
      pageIcon: json['page_icon'],
      pageCategory: json['page_category'],
      permissions: PermissionSet.fromJson(json['permissions']),
    );
  }
}

class PermissionSet {
  final bool canView;
  final bool canCreate;
  final bool canEdit;
  final bool canDelete;
  final bool canExport;
  final bool canImport;
  final Map<String, dynamic> custom;

  PermissionSet({
    required this.canView,
    required this.canCreate,
    required this.canEdit,
    required this.canDelete,
    required this.canExport,
    required this.canImport,
    required this.custom,
  });

  factory PermissionSet.fromJson(Map<String, dynamic> json) {
    return PermissionSet(
      canView: json['can_view'] ?? false,
      canCreate: json['can_create'] ?? false,
      canEdit: json['can_edit'] ?? false,
      canDelete: json['can_delete'] ?? false,
      canExport: json['can_export'] ?? false,
      canImport: json['can_import'] ?? false,
      custom: json['custom'] ?? {},
    );
  }
}

class AuthResponse {
  final String userId;
  final String userType;
  final String role;
  final String firstName;
  final String lastName;
  final String email;
  final String tenantId;
  final List<PagePermission> pagePermissions;
  // ... other fields

  AuthResponse({
    required this.userId,
    required this.userType,
    required this.role,
    required this.firstName,
    required this.lastName,
    required this.email,
    required this.tenantId,
    required this.pagePermissions,
    // ... other fields
  });

  factory AuthResponse.fromJson(Map<String, dynamic> json) {
    return AuthResponse(
      userId: json['user_id'],
      userType: json['user_type'],
      role: json['role'],
      firstName: json['first_name'],
      lastName: json['last_name'],
      email: json['email'],
      tenantId: json['tenant_id'],
      pagePermissions: (json['page_permissions'] as List)
          .map((p) => PagePermission.fromJson(p))
          .toList(),
      // ... other fields
    );
  }
}
```

## 2. Update Navigation Sidebar

Replace your static navigation with dynamic navigation:

```dart
// lib/shared/widgets/navigation_sidebar.dart
class NavigationSidebar extends StatefulWidget {
  final bool isOpen;
  final String userRole;
  final String? userId;
  final String? tenantId;
  final List<PagePermission> pagePermissions; // Add this
  final VoidCallback onClose;
  final VoidCallback onLogout;

  const NavigationSidebar({
    super.key,
    required this.isOpen,
    required this.userRole,
    this.userId,
    this.tenantId,
    required this.pagePermissions, // Add this
    required this.onClose,
    required this.onLogout,
  });

  @override
  State<NavigationSidebar> createState() => _NavigationSidebarState();
}

class _NavigationSidebarState extends State<NavigationSidebar> {
  
  List<NavigationItem> getNavigationItems() {
    // Convert page permissions to navigation items
    return widget.pagePermissions
        .where((permission) => permission.permissions.canView)
        .map((permission) => NavigationItem(
          id: permission.pageId,
          label: permission.pageName,
          icon: _getIconData(permission.pageIcon),
          path: permission.pagePath,
          category: permission.pageCategory,
        ))
        .toList();
  }

  IconData _getIconData(String? iconName) {
    // Map icon names to IconData
    switch (iconName) {
      case 'dashboard':
        return Icons.dashboard;
      case 'person':
        return Icons.person;
      case 'class':
        return Icons.class_;
      case 'access_time':
        return Icons.access_time;
      case 'schedule':
        return Icons.schedule;
      case 'quiz':
        return Icons.quiz;
      case 'assignment':
        return Icons.assignment;
      case 'chat':
        return Icons.chat;
      case 'notifications':
        return Icons.notifications;
      case 'smart_toy':
        return Icons.smart_toy;
      case 'people':
        return Icons.people;
      case 'manage_accounts':
        return Icons.manage_accounts;
      case 'settings':
        return Icons.settings;
      default:
        return Icons.circle;
    }
  }

  // Group items by category
  Map<String, List<NavigationItem>> getGroupedItems() {
    final items = getNavigationItems();
    final grouped = <String, List<NavigationItem>>{};
    
    for (final item in items) {
      final category = item.category ?? 'Other';
      grouped.putIfAbsent(category, () => []).add(item);
    }
    
    return grouped;
  }

  @override
  Widget build(BuildContext context) {
    final groupedItems = getGroupedItems();
    
    return AnimatedBuilder(
      animation: _slideAnimation,
      builder: (context, child) {
        return Positioned(
          left: widget.isOpen ? 0 : -sidebarWidth,
          top: 0,
          bottom: 0,
          child: Material(
            color: Colors.transparent,
            child: Container(
              width: sidebarWidth,
              height: screenSize.height,
              decoration: AppTheme.getMicroDecoration(
                color: Colors.white,
                borderRadius: const BorderRadius.only(
                  topRight: Radius.circular(12),
                  bottomRight: Radius.circular(12),
                ),
                border: Border.all(color: AppTheme.neutral200.withOpacity(0.5)),
              ),
              child: Column(
                children: [
                  Expanded(
                    child: groupedItems.isEmpty
                        ? _buildEmptyState(context)
                        : _buildGroupedNavigationList(context, groupedItems),
                  ),
                  _buildUserSection(context),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildGroupedNavigationList(
    BuildContext context,
    Map<String, List<NavigationItem>> groupedItems,
  ) {
    return ListView(
      padding: const EdgeInsets.symmetric(vertical: 4),
      children: groupedItems.entries.map((entry) {
        final category = entry.key;
        final items = entry.value;
        
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (category != 'Main') // Don't show category header for main items
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                child: Text(
                  category,
                  style: AppTheme.labelSmall.copyWith(
                    color: AppTheme.neutral500,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ...items.map((item) => _buildNavigationItem(context, item)),
            const SizedBox(height: 8),
          ],
        );
      }).toList(),
    );
  }

  Widget _buildNavigationItem(BuildContext context, NavigationItem item) {
    final targetUrl = _buildUrlWithParams(item.path);
    final targetPath = Uri.parse(targetUrl).path;
    final currentPath = Uri.parse(currentLocation).path;
    final isActive = currentPath == targetPath;

    return Container(
      height: 36,
      margin: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      child: InkWell(
        onTap: () => context.go(targetUrl),
        borderRadius: AppTheme.borderRadius8,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          decoration: BoxDecoration(
            gradient: isActive ? AppTheme.primaryGradient : null,
            borderRadius: AppTheme.borderRadius8,
            boxShadow: isActive ? [AppTheme.microShadow] : null,
          ),
          child: Row(
            children: [
              Icon(
                item.icon,
                color: isActive ? Colors.white : AppTheme.neutral600,
                size: 16,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  item.label,
                  style: AppTheme.bodyMicro.copyWith(
                    color: isActive ? Colors.white : AppTheme.neutral700,
                    fontWeight: isActive ? FontWeight.w600 : FontWeight.w500,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
```

## 3. Update Main Layout

Update your main layout to pass page permissions:

```dart
// lib/shared/widgets/main_layout.dart
class MainLayout extends StatefulWidget {
  final String userRole;
  final String? tenantId;
  final String? userId;
  final List<PagePermission> pagePermissions; // Add this
  final Widget child;

  const MainLayout({
    super.key,
    required this.userRole,
    this.tenantId,
    this.userId,
    required this.pagePermissions, // Add this
    required this.child,
  });

  @override
  State<MainLayout> createState() => _MainLayoutState();
}

class _MainLayoutState extends State<MainLayout> {
  bool _isSidebarOpen = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        children: [
          // Main content
          widget.child,
          
          // Navigation sidebar
          NavigationSidebar(
            isOpen: _isSidebarOpen,
            userRole: widget.userRole,
            userId: widget.userId,
            tenantId: widget.tenantId,
            pagePermissions: widget.pagePermissions, // Pass permissions
            onClose: () => setState(() => _isSidebarOpen = false),
            onLogout: _handleLogout,
          ),
          
          // Overlay when sidebar is open
          if (_isSidebarOpen)
            GestureDetector(
              onTap: () => setState(() => _isSidebarOpen = false),
              child: Container(
                color: Colors.black.withOpacity(0.3),
              ),
            ),
        ],
      ),
    );
  }

  void _handleLogout() {
    // Handle logout logic
  }
}
```

## 4. Update App Router

Update your app router to pass page permissions:

```dart
// lib/core/utils/app_router.dart
final GoRouter appRouter = GoRouter(
  initialLocation: AppConstants.homeRoute,
  routes: [
    // ... other routes
    
    ShellRoute(
      builder: (context, state, child) {
        // Get page permissions from your auth state/provider
        final pagePermissions = AuthProvider.of(context).pagePermissions;
        
        return MainLayout(
          userRole: state.uri.queryParameters['role'] ?? 'student',
          tenantId: state.uri.queryParameters['tenantId'],
          userId: state.uri.queryParameters['userId'],
          pagePermissions: pagePermissions, // Pass permissions
          child: child,
        );
      },
      routes: [
        // Your existing routes
      ],
    ),
  ],
);
```

## 5. Permission Checking Utilities

Create utilities for checking permissions:

```dart
// lib/utils/permission_utils.dart
class PermissionUtils {
  static bool canUserViewPage(String pageId, List<PagePermission> permissions) {
    final permission = permissions.firstWhere(
      (p) => p.pageId == pageId,
      orElse: () => null,
    );
    return permission?.permissions.canView ?? false;
  }

  static bool canUserEditPage(String pageId, List<PagePermission> permissions) {
    final permission = permissions.firstWhere(
      (p) => p.pageId == pageId,
      orElse: () => null,
    );
    return permission?.permissions.canEdit ?? false;
  }

  static bool canUserCreateOnPage(String pageId, List<PagePermission> permissions) {
    final permission = permissions.firstWhere(
      (p) => p.pageId == pageId,
      orElse: () => null,
    );
    return permission?.permissions.canCreate ?? false;
  }

  static bool canUserDeleteOnPage(String pageId, List<PagePermission> permissions) {
    final permission = permissions.firstWhere(
      (p) => p.pageId == pageId,
      orElse: () => null,
    );
    return permission?.permissions.canDelete ?? false;
  }

  static List<PagePermission> getPagesByCategory(
    String category, 
    List<PagePermission> permissions
  ) {
    return permissions
        .where((p) => p.pageCategory == category && p.permissions.canView)
        .toList();
  }
}
```

## 6. Using Permissions in UI

Use permissions to conditionally show UI elements:

```dart
// Example usage in a screen
class StudentDashboardScreen extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final authProvider = AuthProvider.of(context);
    final permissions = authProvider.pagePermissions;

    return Scaffold(
      appBar: AppBar(
        title: Text('Dashboard'),
        actions: [
          // Only show settings if user can access system settings
          if (PermissionUtils.canUserViewPage('system-settings', permissions))
            IconButton(
              icon: Icon(Icons.settings),
              onPressed: () => context.go('/settings'),
            ),
        ],
      ),
      body: Column(
        children: [
          // Only show create button if user can create
          if (PermissionUtils.canUserCreateOnPage('dashboard', permissions))
            ElevatedButton(
              onPressed: () => _createNewItem(),
              child: Text('Create New'),
            ),
          
          // Show different content based on permissions
          Expanded(
            child: ListView(
              children: [
                // Always visible content
                _buildWelcomeCard(),
                
                // Conditional content based on permissions
                if (PermissionUtils.canUserViewPage('classes', permissions))
                  _buildClassesCard(),
                
                if (PermissionUtils.canUserViewPage('assessments', permissions))
                  _buildAssessmentsCard(),
                
                if (PermissionUtils.canUserViewPage('attendance', permissions))
                  _buildAttendanceCard(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
```

## 7. Auth Service Update

Update your auth service to handle the new response:

```dart
// lib/services/auth_service.dart
class AuthService {
  static Future<AuthResponse?> getUserProfile(String userId, String tenantId) async {
    try {
      final response = await http.get(
        Uri.parse('${ApiConstants.baseUrl}/api/auth/user-profile/$userId?tenant_id=$tenantId'),
        headers: {'Content-Type': 'application/json'},
      );

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        return AuthResponse.fromJson(data);
      }
      return null;
    } catch (e) {
      print('Error getting user profile: $e');
      return null;
    }
  }
}
```

## Summary

With these changes, your Flutter app will:

1. ✅ Dynamically build navigation based on user permissions
2. ✅ Show/hide UI elements based on permissions
3. ✅ Group navigation items by category
4. ✅ Support granular permission checking
5. ✅ Handle the new auth response format

The system is now fully dynamic and will automatically adapt to permission changes made in the backend without requiring app updates!