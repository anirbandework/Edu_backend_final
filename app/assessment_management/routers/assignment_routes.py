# app/assessment_management/routers/assignment_routes.py
#
# Assignment (Assessment) CRUD. The `assessments` table + model already existed;
# only these routes were missing, leaving the submit/grade flow with no parent
# entity. Create auto-resolves (or creates) the Subject by name so the NOT-NULL
# subject_id FK is satisfied without a separate subjects-management flow.
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.access.deps import require_authority_or_module
from ...auth_rbac.security.principal import Principal
from ..models.grading_system_models import (
    Assessment, AssessmentType, AssessmentStatus, AssessmentSubmission,
)
from ...timetable_management.models.timetable import Subject
from ...enrollment_management.models.enrollment import Enrollment

router = APIRouter(prefix="/assignments", tags=["Assignments"])


class AssignmentCreate(BaseModel):
    class_id: UUID
    assessment_title: str
    subject: str                       # subject NAME (resolved/created to a subject_id)
    assessment_type: str = "assignment"
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    max_marks: float = 100
    academic_year: str
    allow_late_submission: bool = False


def _coerce_atype(v: str) -> AssessmentType:
    try:
        return AssessmentType(v)
    except ValueError:
        return AssessmentType.assignment


def _assessment_dict(a: Assessment, subject_name: Optional[str]) -> dict:
    return {
        "id": str(a.id),
        "assessment_title": a.assessment_title,
        "assessment_type": a.assessment_type.value if a.assessment_type else None,
        "subject": subject_name,
        "description": a.description,
        "due_date": a.due_date.isoformat() if a.due_date else None,
        "max_marks": float(a.max_marks) if a.max_marks is not None else None,
        "academic_year": a.academic_year,
        "class_id": str(a.class_id),
        "status": a.status.value if a.status else None,
        "allow_late_submission": a.allow_late_submission,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


async def _get_or_create_subject(db: AsyncSession, tenant_id: UUID, name: str,
                                 academic_year: str) -> UUID:
    name = name.strip()
    res = await db.execute(
        select(Subject).where(
            and_(
                Subject.tenant_id == tenant_id,
                func.lower(Subject.subject_name) == name.lower(),
                Subject.is_deleted == False,
            )
        ).limit(1)
    )
    subj = res.scalars().first()
    if subj:
        return subj.id
    code = (name[:8].upper().replace(" ", "") or "SUBJ")
    subj = Subject(
        tenant_id=tenant_id, subject_name=name, subject_code=code,
        academic_year=academic_year, periods_per_week=5, is_active=True,
    )
    db.add(subj)
    await db.flush()
    return subj.id


@router.post("")
async def create_assignment(
    payload: AssignmentCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('assignments')),
):
    """Create an assignment for a class. teacher_id is the authenticated teacher;
    subject is resolved/created by name. Published immediately so students see it."""
    if principal.is_super_admin:
        raise HTTPException(status_code=400, detail="Super-admin must use a tenant context")
    tenant_id = UUID(str(principal.tenant_id))
    subject_id = await _get_or_create_subject(db, tenant_id, payload.subject, payload.academic_year)
    a = Assessment(
        tenant_id=tenant_id,
        subject_id=subject_id,
        class_id=payload.class_id,
        teacher_id=UUID(str(principal.user_id)),
        assessment_title=payload.assessment_title,
        assessment_type=_coerce_atype(payload.assessment_type),
        description=payload.description,
        due_date=payload.due_date,
        max_marks=payload.max_marks,
        academic_year=payload.academic_year,
        allow_late_submission=payload.allow_late_submission,
        status=AssessmentStatus.published,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return {"id": str(a.id), "assessment_title": a.assessment_title,
            "status": a.status.value, "message": "Assignment created"}


@router.get("/class/{class_id}")
async def list_class_assignments(
    class_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """All assignments for a class (teacher/admin view)."""
    q = select(Assessment, Subject.subject_name).join(
        Subject, Subject.id == Assessment.subject_id, isouter=True
    ).where(and_(Assessment.class_id == class_id, Assessment.is_deleted == False))
    if not principal.is_super_admin:
        q = q.where(Assessment.tenant_id == UUID(str(principal.tenant_id)))
    q = q.order_by(Assessment.created_at.desc())
    rows = (await db.execute(q)).all()
    return [_assessment_dict(a, subj) for a, subj in rows]


@router.get("/student/{student_id}")
async def list_student_assignments(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Assignments for a student's enrolled classes, each with the student's own
    submission status. Students are forced to themselves."""
    if principal.role == "student":
        student_id = UUID(str(principal.user_id))
    tenant_id = None if principal.is_super_admin else UUID(str(principal.tenant_id))

    class_rows = await db.execute(
        select(Enrollment.class_id).where(
            and_(
                Enrollment.member_id == student_id,  # enrolment keys on members.id now
                Enrollment.status == "active",
                Enrollment.is_deleted == False,
            )
        )
    )
    class_ids = [r[0] for r in class_rows.all()]
    if not class_ids:
        return []

    q = select(Assessment, Subject.subject_name).join(
        Subject, Subject.id == Assessment.subject_id, isouter=True
    ).where(and_(
        Assessment.class_id.in_(class_ids),
        Assessment.is_deleted == False,
        Assessment.status != AssessmentStatus.draft,
    ))
    if tenant_id is not None:
        q = q.where(Assessment.tenant_id == tenant_id)
    q = q.order_by(Assessment.created_at.desc())
    rows = (await db.execute(q)).all()

    out: List[dict] = []
    for a, subj in rows:
        sub = (await db.execute(
            select(AssessmentSubmission).where(and_(
                AssessmentSubmission.assessment_id == a.id,
                AssessmentSubmission.student_id == student_id,
                AssessmentSubmission.is_deleted == False,
            )).limit(1)
        )).scalars().first()
        d = _assessment_dict(a, subj)
        d["submission"] = None if not sub else {
            "submission_id": str(sub.id),
            "status": sub.status.value if sub.status else None,
            "is_graded": sub.is_graded,
            "marks_obtained": float(sub.marks_obtained) if sub.marks_obtained is not None else None,
            "grade_letter": sub.grade_letter,
            "teacher_feedback": sub.teacher_feedback,
        }
        out.append(d)
    return out


@router.get("/{assessment_id}")
async def get_assignment(
    assessment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """A single assignment."""
    row = (await db.execute(
        select(Assessment, Subject.subject_name).join(
            Subject, Subject.id == Assessment.subject_id, isouter=True
        ).where(Assessment.id == assessment_id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
    a, subj = row
    if not principal.is_super_admin and str(a.tenant_id) != str(principal.tenant_id):
        raise HTTPException(status_code=404, detail="Assignment not found")
    return _assessment_dict(a, subj)
