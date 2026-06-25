# app/models/tenant_specific/notification.py
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Text, Enum
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from ...models.base import Base
import enum


class NotificationType(enum.Enum):
    ANNOUNCEMENT = "announcement"
    URGENT = "urgent"
    ASSIGNMENT = "assignment"
    GRADE = "grade"
    ATTENDANCE = "attendance"
    EVENT = "event"
    REMINDER = "reminder"
    DISCIPLINARY = "disciplinary"
    SYSTEM = "system"
    PERSONAL = "personal"
    MAINTENANCE = "maintenance"
    HOLIDAY = "holiday"


class NotificationPriority(enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class NotificationStatus(enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    ARCHIVED = "archived"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryChannel(enum.Enum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WHATSAPP = "whatsapp"
    SLACK = "slack"


class RecipientType(enum.Enum):
    INDIVIDUAL = "individual"
    CLASS = "class"
    GRADE = "grade"
    ALL_STUDENTS = "all_students"
    ALL_TEACHERS = "all_teachers"
    ALL_STAFF = "all_staff"
    ALL_SCHOOL_AUTHORITIES = "all_school_authorities"
    ALL_INSTITUTION = "all_institution"
    DEPARTMENT = "department"
    CUSTOM_GROUP = "custom_group"
    PARENTS = "parents"
    ALL_USERS = "all_users"


class SenderType(enum.Enum):
    SCHOOL_AUTHORITY = "school_authority"
    TEACHER = "teacher"
    SYSTEM = "system"
    ADMIN = "admin"


class Notification(Base):
    __tablename__ = "notifications"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    sender_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # Polymorphic - can reference any user type
    sender_type = Column(
        Enum(
            SenderType,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        nullable=False
    )
    
    # Notification Content
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    short_message = Column(String(500))  # For SMS/push notifications
    notification_type = Column(
        Enum(
            NotificationType,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        nullable=False
    )
    priority = Column(
        Enum(
            NotificationPriority,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        default=NotificationPriority.NORMAL.value,
        nullable=False
    )
    
    # Recipient Configuration
    recipient_type = Column(
        Enum(
            RecipientType,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        nullable=False
    )
    recipient_config = Column(JSON)  # Configuration for recipients
    
    # Delivery Configuration  
    delivery_channels = Column(JSON)  # List of channels to use
    scheduled_at = Column(DateTime)  # For scheduled notifications
    expires_at = Column(DateTime)    # When notification expires
    
    # Content and Media
    attachments = Column(JSON)  # File attachments
    action_url = Column(String(500))  # URL for call-to-action
    action_text = Column(String(100))  # Text for action button
    rich_content = Column(JSON)  # Rich content formatting
    
    # Delivery Tracking
    total_recipients = Column(Integer, default=0)
    delivered_count = Column(Integer, default=0)
    read_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    clicked_count = Column(Integer, default=0)
    
    # Status and Timing
    status = Column(
        Enum(
            NotificationStatus,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        default=NotificationStatus.DRAFT.value,
        nullable=False
    )
    sent_at = Column(DateTime)
    delivery_started_at = Column(DateTime)
    delivery_completed_at = Column(DateTime)
    
    # Additional Information
    category = Column(String(50))  # Custom categorization
    tags = Column(JSON)  # Tags for organization
    extra_data = Column(JSON)  # CHANGED FROM 'metadata' to 'extra_data'
    
    # Academic Context
    academic_year = Column(String(10))
    term = Column(String(20))
    subject_id = Column(UUID(as_uuid=True))  # Removed ForeignKey for flexibility
    class_id = Column(UUID(as_uuid=True))   # Removed ForeignKey for flexibility
    
    # Auto-deletion and Archival
    auto_delete_at = Column(DateTime)
    auto_archive_at = Column(DateTime)
    
    # Analytics
    open_rate = Column(Integer, default=0)
    click_rate = Column(Integer, default=0)
    
    # Relationships
    tenant = relationship("Tenant")
    recipients = relationship("NotificationRecipient", back_populates="notification", cascade="all, delete-orphan")
    delivery_logs = relationship("NotificationDeliveryLog", back_populates="notification", cascade="all, delete-orphan")


class NotificationRecipient(Base):
    __tablename__ = "notification_recipients"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    notification_id = Column(UUID(as_uuid=True), ForeignKey("notifications.id"), nullable=False, index=True)
    recipient_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    recipient_type = Column(String(20), nullable=False)  # "student", "teacher", "parent"
    
    # Personal Information (for quick access)
    recipient_name = Column(String(200))
    recipient_email = Column(String(200))
    recipient_phone = Column(String(20))
    
    # Delivery Status
    status = Column(
        Enum(
            NotificationStatus,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        default=NotificationStatus.SENT.value,
        nullable=False
    )
    delivered_at = Column(DateTime)
    read_at = Column(DateTime)
    clicked_at = Column(DateTime)
    
    # Channel-specific delivery status
    delivery_status = Column(JSON)
    preferred_channels = Column(JSON)
    
    # User Actions
    is_starred = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    
    # Response/Interaction
    has_responded = Column(Boolean, default=False)
    response_data = Column(JSON)
    interaction_count = Column(Integer, default=0)
    
    # Device Information
    device_info = Column(JSON)
    last_seen_at = Column(DateTime)
    
    # Relationships
    tenant = relationship("Tenant")
    notification = relationship("Notification", back_populates="recipients")


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_by_type = Column(
        Enum(
            SenderType,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        nullable=False
    )
    
    # Template Information
    template_name = Column(String(100), nullable=False)
    template_code = Column(String(50), nullable=False, index=True)
    description = Column(Text)
    version = Column(String(10), default="1.0")
    
    # Template Content
    subject_template = Column(String(200), nullable=False)
    body_template = Column(Text, nullable=False)
    short_message_template = Column(String(500))  # For SMS/push
    
    # Template Configuration
    notification_type = Column(
        Enum(
            NotificationType,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        nullable=False
    )
    default_priority = Column(
        Enum(
            NotificationPriority,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        default=NotificationPriority.NORMAL.value,
        nullable=False
    )
    supported_channels = Column(JSON)
    
    # Variables and Placeholders
    template_variables = Column(JSON)
    sample_data = Column(JSON)
    validation_rules = Column(JSON)
    
    # Usage and Status
    is_active = Column(Boolean, default=True)
    is_system_template = Column(Boolean, default=False)
    usage_count = Column(Integer, default=0)
    
    # Categories and Organization
    category = Column(String(50))
    tags = Column(JSON)
    
    # Relationships
    tenant = relationship("Tenant")


class NotificationDeliveryLog(Base):
    __tablename__ = "notification_delivery_logs"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    notification_id = Column(UUID(as_uuid=True), ForeignKey("notifications.id"), nullable=False, index=True)
    recipient_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Delivery Information
    channel = Column(
        Enum(
            DeliveryChannel,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        nullable=False
    )
    delivery_attempt = Column(Integer, default=1)
    
    # Status and Timing
    status = Column(String(20), nullable=False)
    attempted_at = Column(DateTime, nullable=False)
    delivered_at = Column(DateTime)
    processed_at = Column(DateTime)
    
    # Channel-specific Information
    channel_identifier = Column(String(200))  # Email, phone, device token
    external_reference = Column(String(100))  # External service reference
    provider = Column(String(50))  # SendGrid, Twilio, etc.
    
    # Error Information
    error_code = Column(String(50))
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    next_retry_at = Column(DateTime)
    
    # Response Information
    response_data = Column(JSON)
    delivery_cost = Column(Integer, default=0)  # Cost in cents
    
    # Relationships
    tenant = relationship("Tenant")
    notification = relationship("Notification", back_populates="delivery_logs")


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_type = Column(String(20), nullable=False)
    
    # Preference Configuration
    notification_type = Column(
        Enum(
            NotificationType,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        nullable=False
    )
    
    # Channel Preferences
    email_enabled = Column(Boolean, default=True)
    sms_enabled = Column(Boolean, default=False)
    push_enabled = Column(Boolean, default=True)
    in_app_enabled = Column(Boolean, default=True)
    whatsapp_enabled = Column(Boolean, default=False)
    
    # Advanced Channel Settings
    channel_preferences = Column(JSON)  # Advanced per-channel settings
    
    # Timing Preferences
    quiet_hours_start = Column(String(5))  # "22:00"
    quiet_hours_end = Column(String(5))    # "08:00"
    timezone = Column(String(50), default="UTC")
    
    # Frequency Limits
    max_daily_notifications = Column(Integer, default=50)
    max_weekly_digest = Column(Boolean, default=True)
    digest_day = Column(String(10), default="sunday")
    
    # Priority Filtering
    min_priority = Column(
        Enum(
            NotificationPriority,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        default=NotificationPriority.LOW.value,
        nullable=False
    )
    
    # Content Filtering
    keywords_filter = Column(JSON)  # Keywords to filter
    sender_whitelist = Column(JSON)  # Allowed senders
    sender_blacklist = Column(JSON)  # Blocked senders
    
    # Relationships
    tenant = relationship("Tenant")


class NotificationGroup(Base):
    __tablename__ = "notification_groups"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_by_type = Column(
        Enum(
            SenderType,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        nullable=False
    )
    
    # Group Information
    group_name = Column(String(100), nullable=False)
    group_code = Column(String(50), nullable=False)
    description = Column(Text)
    group_color = Column(String(7), default="#007bff")  # Hex color
    
    # Group Configuration
    group_type = Column(String(20), nullable=False)  # "static", "dynamic"
    members = Column(JSON)  # Static members
    criteria = Column(JSON)  # Dynamic criteria
    
    # Member counts
    total_members = Column(Integer, default=0)
    active_members = Column(Integer, default=0)
    
    # Status and Access
    is_active = Column(Boolean, default=True)
    is_public = Column(Boolean, default=False)
    access_level = Column(String(20), default="private")
    
    # Auto-refresh for dynamic groups
    last_refreshed_at = Column(DateTime)
    auto_refresh_interval = Column(Integer, default=24)  # Hours
    
    # Relationships
    tenant = relationship("Tenant")


class NotificationSchedule(Base):
    __tablename__ = "notification_schedules"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    notification_template_id = Column(UUID(as_uuid=True), ForeignKey("notification_templates.id"), nullable=False)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    
    # Schedule Information
    schedule_name = Column(String(100), nullable=False)
    description = Column(Text)
    
    # Timing Configuration
    schedule_type = Column(String(20), nullable=False)  # "once", "daily", "weekly", "monthly"
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime)
    
    # Recurrence Pattern
    recurrence_pattern = Column(JSON)
    timezone = Column(String(50), default="UTC")
    
    # Recipients
    recipient_config = Column(JSON)
    
    # Execution Status
    is_active = Column(Boolean, default=True)
    next_run = Column(DateTime)
    last_run = Column(DateTime)
    run_count = Column(Integer, default=0)
    max_runs = Column(Integer)  # Maximum executions
    
    # Error Handling
    max_failures = Column(Integer, default=3)
    failure_count = Column(Integer, default=0)
    last_error = Column(Text)
    
    # Relationships
    tenant = relationship("Tenant")
    template = relationship("NotificationTemplate")


class NotificationBatch(Base):
    __tablename__ = "notification_batches"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_by_type = Column(
        Enum(
            SenderType,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        nullable=False
    )
    
    # Batch Information
    batch_name = Column(String(100), nullable=False)
    batch_type = Column(String(20), nullable=False)  # "import", "campaign", "emergency"
    description = Column(Text)
    
    # Processing Status
    status = Column(String(20), default="pending")  # pending, processing, completed, failed
    total_notifications = Column(Integer, default=0)
    processed_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    
    # Timing
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    estimated_completion = Column(DateTime)
    
    # Configuration
    batch_config = Column(JSON)  # Batch-specific configuration
    
    # Progress Tracking
    progress_percentage = Column(Integer, default=0)
    current_phase = Column(String(50))
    
    # Results
    results_summary = Column(JSON)
    error_log = Column(JSON)
    
    # Relationships
    tenant = relationship("Tenant")
