# app/models/__init__.py
"""Import all models here, if needed for Alembic migration."""
from .base import Base

# Shared models
from .shared.tenant import Tenant

# Tenant-specific models
from .tenant_specific.school_authority import SchoolAuthority
from .tenant_specific.teacher import Teacher
from .tenant_specific.student import Student
from .tenant_specific.class_model import ClassModel
from .tenant_specific.enrollment import Enrollment
from .tenant_specific.attendance import Attendance, AttendanceSummary, AttendancePolicy, AttendanceReport, AttendanceAlert
from .tenant_specific.notification import Notification
from .tenant_specific.timetable import (
    MasterTimetable, Period, ClassTimetable, TeacherTimetable, 
    ScheduleEntry, TimetableConflict, Subject, TimetableTemplate,
    TimetableAuditLog
)

# Exam management models
from .tenant_specific.exam_management import (
    Exam, ExamClass, StudentExamMark, ExamTemplate, BulkMarkingBatch
)

# Role management models
from .role_management import Role, UserRole

# This ensures all models are loaded when importing models
