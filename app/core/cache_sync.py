# app/models/tenant_specific/cache_sync.py
from sqlalchemy import event
from sqlalchemy.orm import Session

def sync_cached_fields():
    """Sync cached fields when related data changes"""
    
    @event.listens_for(Session, 'before_flush')
    def sync_cache_on_flush(session, flush_context, instances):
        for obj in session.dirty:
            # Sync teacher_name in TeacherTimetable and ScheduleEntry
            if hasattr(obj, 'teacher_name') and hasattr(obj, 'teacher_id'):
                if obj.teacher and obj.teacher.full_name != obj.teacher_name:
                    obj.teacher_name = obj.teacher.full_name
            
            # Sync class_name in ClassTimetable
            if hasattr(obj, 'class_name') and hasattr(obj, 'class_id'):
                if obj.class_model and obj.class_model.class_name != obj.class_name:
                    obj.class_name = obj.class_model.class_name
            
            # Sync subject_name in ScheduleEntry
            if hasattr(obj, 'subject_name') and hasattr(obj, 'subject_id'):
                if obj.subject and obj.subject.subject_name != obj.subject_name:
                    obj.subject_name = obj.subject.subject_name