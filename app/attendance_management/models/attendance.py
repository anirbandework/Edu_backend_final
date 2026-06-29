# app/models/tenant_specific/attendance.py
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Time, Text, Enum, Date
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from ...models.base import Base
import enum
from datetime import datetime


class AttendanceStatus(enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"
    SICK = "sick"
    PARTIAL = "partial"
    EARLY_DEPARTURE = "early_departure"
    SUSPENDED = "suspended"


class AttendanceType(enum.Enum):
    DAILY = "daily"
    PERIOD = "period"
    EVENT = "event"
    EXAM = "exam"
    ASSEMBLY = "assembly"
    EXTRACURRICULAR = "extracurricular"


class UserType(enum.Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    SCHOOL_AUTHORITY = "school_authority"
    STAFF = "staff"


class AttendanceMode(enum.Enum):
    MANUAL = "manual"
    BIOMETRIC = "biometric"
    QR_CODE = "qr_code"
    MOBILE_APP = "mobile_app"
    RFID = "rfid"


class Attendance(Base):
    __tablename__ = "attendances"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # Polymorphic - can be student, teacher, or authority
    user_type = Column(Enum(UserType), nullable=False)
    class_id = Column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=True, index=True)
    marked_by = Column(UUID(as_uuid=True), nullable=False, index=True)  # Polymorphic - who marked attendance
    marked_by_type = Column(Enum(UserType), nullable=False)
    
    # Attendance Information
    attendance_date = Column(Date, nullable=False, index=True)
    attendance_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    attendance_type = Column(Enum(AttendanceType), default=AttendanceType.DAILY, nullable=False)
    attendance_mode = Column(Enum(AttendanceMode), default=AttendanceMode.MANUAL, nullable=False)
    status = Column(Enum(AttendanceStatus), default=AttendanceStatus.PRESENT, nullable=False)
    
    # Time Information
    check_in_time = Column(Time)
    check_out_time = Column(Time)
    expected_check_in = Column(Time)
    expected_check_out = Column(Time)
    actual_hours = Column(Integer)  # Minutes spent
    
    # Additional Details
    period_number = Column(Integer)  # For period-wise attendance
    subject_id = Column(UUID(as_uuid=True))  # Subject being taught
    subject_name = Column(String(100))
    location = Column(String(100))  # Classroom, lab, etc.
    remarks = Column(Text)
    reason_for_absence = Column(String(500))
    is_excused = Column(Boolean, default=False)
    
    # Approval Information
    approved_by = Column(UUID(as_uuid=True))  # Polymorphic - can be any user type
    approved_by_type = Column(Enum(UserType))
    approval_date = Column(DateTime)
    approval_remarks = Column(Text)
    
    # Academic Information
    academic_year = Column(String(10), nullable=False, index=True)
    term = Column(String(20))  # "Term 1", "Term 2", etc.
    week_number = Column(Integer)
    semester = Column(String(20))
    
    # Geolocation (for mobile attendance)
    latitude = Column(String(20))
    longitude = Column(String(20))
    location_accuracy = Column(Integer)  # In meters
    
    # Device Information
    device_info = Column(JSON)  # Device used to mark attendance
    ip_address = Column(String(45))
    
    # Batch Information (for bulk operations)
    batch_id = Column(UUID(as_uuid=True))
    import_source = Column(String(50))  # "bulk_upload", "biometric_sync", etc.
    
    # Relationships
    tenant = relationship("Tenant")
    class_ref = relationship("ClassModel", back_populates="attendances")


class AttendanceSummary(Base):
    __tablename__ = "attendance_summaries"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_type = Column(Enum(UserType), nullable=False)
    class_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    
    # Summary Period
    summary_type = Column(String(20), nullable=False)  # "daily", "weekly", "monthly", "term", "annual"
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    academic_year = Column(String(10), nullable=False)
    
    # Statistics
    total_days = Column(Integer, default=0)
    working_days = Column(Integer, default=0)  # Expected working days
    present_days = Column(Integer, default=0)
    absent_days = Column(Integer, default=0)
    late_days = Column(Integer, default=0)
    excused_days = Column(Integer, default=0)
    sick_days = Column(Integer, default=0)
    early_departure_days = Column(Integer, default=0)
    
    # Time-based Statistics
    total_hours_present = Column(Integer, default=0)  # In minutes
    average_check_in_time = Column(Time)
    average_check_out_time = Column(Time)
    
    # Calculated Fields
    attendance_percentage = Column(Integer, default=0)  # 0-100
    punctuality_percentage = Column(Integer, default=0)  # On-time arrivals
    
    # Status Flags
    is_below_threshold = Column(Boolean, default=False)
    requires_attention = Column(Boolean, default=False)
    
    # Last Updated
    last_calculated = Column(DateTime, default=datetime.utcnow)
    calculation_method = Column(String(20), default="automatic")
    
    # Relationships
    tenant = relationship("Tenant")


class AttendancePolicy(Base):
    __tablename__ = "attendance_policies"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    
    # Policy Information
    policy_name = Column(String(100), nullable=False)
    description = Column(Text)
    user_type = Column(Enum(UserType), nullable=False)  # Who this policy applies to
    is_active = Column(Boolean, default=True)
    
    # Time Rules for Students
    school_start_time = Column(Time)
    school_end_time = Column(Time)
    lunch_start_time = Column(Time)
    lunch_end_time = Column(Time)
    
    # Time Rules for Staff/Teachers
    office_start_time = Column(Time)
    office_end_time = Column(Time)
    minimum_working_hours = Column(Integer, default=480)  # Minutes per day
    
    # Lateness Rules
    late_threshold_minutes = Column(Integer, default=15)
    grace_period_minutes = Column(Integer, default=5)
    early_departure_threshold = Column(Integer, default=30)
    
    # Attendance Rules
    minimum_attendance_percentage = Column(Integer, default=75)
    consecutive_absent_alert = Column(Integer, default=3)
    monthly_absent_limit = Column(Integer, default=5)
    
    # Leave Rules
    sick_leave_limit_per_month = Column(Integer, default=3)
    casual_leave_limit_per_month = Column(Integer, default=2)
    requires_medical_certificate_after_days = Column(Integer, default=3)
    
    # Notification Rules
    notify_parents_after_absent_days = Column(Integer, default=1)
    notify_administration_after_days = Column(Integer, default=3)
    send_daily_summary = Column(Boolean, default=True)
    send_weekly_report = Column(Boolean, default=True)
    
    # Geolocation Rules
    enable_location_tracking = Column(Boolean, default=False)
    allowed_radius_meters = Column(Integer, default=100)
    school_latitude = Column(String(20))
    school_longitude = Column(String(20))
    
    # Academic Year
    academic_year = Column(String(10), nullable=False)
    effective_from = Column(DateTime, nullable=False)
    effective_until = Column(DateTime)
    
    # Advanced Settings
    allow_retroactive_marking = Column(Boolean, default=True)
    retroactive_days_limit = Column(Integer, default=7)
    require_approval_for_excused = Column(Boolean, default=True)
    
    # Relationships
    tenant = relationship("Tenant")


class AttendanceReport(Base):
    __tablename__ = "attendance_reports"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    generated_by = Column(UUID(as_uuid=True), nullable=False)
    generated_by_type = Column(Enum(UserType), nullable=False)
    
    # Report Information
    report_name = Column(String(100), nullable=False)
    report_type = Column(String(50), nullable=False)  # "daily", "weekly", "monthly", "custom"
    description = Column(Text)
    
    # Report Parameters
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    user_type_filter = Column(Enum(UserType))
    class_ids = Column(JSON)  # List of class IDs
    user_ids = Column(JSON)  # List of specific user IDs
    
    # Report Data
    report_data = Column(JSON)  # Generated report data
    summary_stats = Column(JSON)  # Summary statistics
    
    # Status
    status = Column(String(20), default="pending")  # "pending", "processing", "completed", "failed"
    file_path = Column(String(500))  # Path to generated file (PDF, Excel)
    file_format = Column(String(10))  # "pdf", "excel", "csv"
    
    # Timing
    requested_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    expires_at = Column(DateTime)
    
    # Relationships
    tenant = relationship("Tenant")


class AttendanceAlert(Base):
    __tablename__ = "attendance_alerts"
    
    # Foreign Keys
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_type = Column(Enum(UserType), nullable=False)
    
    # Alert Information
    alert_type = Column(String(50), nullable=False)  # "consecutive_absent", "low_attendance", "late_frequent"
    alert_level = Column(String(20), default="warning")  # "info", "warning", "critical"
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    
    # Alert Data
    trigger_data = Column(JSON)  # Data that triggered the alert
    threshold_value = Column(Integer)
    current_value = Column(Integer)
    
    # Status
    status = Column(String(20), default="active")  # "active", "acknowledged", "resolved", "dismissed"
    acknowledged_by = Column(UUID(as_uuid=True))
    acknowledged_at = Column(DateTime)
    resolved_at = Column(DateTime)
    
    # Academic Context
    academic_year = Column(String(10), nullable=False)
    class_id = Column(UUID(as_uuid=True))
    
    # Relationships
    tenant = relationship("Tenant")
