from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from uuid import UUID, uuid4
from typing import List, Dict, Any
from datetime import datetime
import json
import logging

from app.core.database import get_db
from ...auth_rbac.security.deps import get_current_principal, require_staff
from ...auth_rbac.security.principal import Principal

router = APIRouter(prefix="/cbse-quiz", tags=["CBSE Quiz Platform"])
logger = logging.getLogger(__name__)


async def _assert_attempt_access(db: AsyncSession, principal: Principal, attempt_id, allow_staff: bool):
    """Load an attempt and verify the principal may act on it. Returns (student_id, tenant_id).
    Students may only touch their OWN attempt; staff (when allow_staff) may within their tenant."""
    row = (await db.execute(
        text("SELECT student_id, tenant_id FROM quiz_attempts WHERE id = :a AND is_deleted = false"),
        {"a": str(attempt_id)},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Quiz attempt not found")
    student_id, tenant_id = str(row[0]), str(row[1])
    if principal.is_super_admin:
        return student_id, tenant_id
    if principal.tenant_id and tenant_id != str(principal.tenant_id):
        raise HTTPException(status_code=403, detail="Cross-tenant access denied")
    if allow_staff and principal.is_staff:
        return student_id, tenant_id
    if student_id != str(principal.user_id):
        raise HTTPException(status_code=403, detail="Not your attempt")
    return student_id, tenant_id


@router.post("/create-quiz")
async def create_cbse_quiz(
    subject: str,
    title: str,
    tenant_id: UUID,
    class_id: UUID,
    teacher_id: UUID,
    time_limit: int = 60,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),  # authoring: staff only
):
    """Create CBSE subject quiz"""
    # Bind tenant + owning teacher to the principal; never trust client ids.
    eff_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    eff_teacher = teacher_id if principal.is_super_admin else UUID(str(principal.user_id))

    quiz_id = str(uuid4())
    topic_id = str(uuid4())

    await db.execute(text("""
        INSERT INTO topics (id, tenant_id, name, description, subject, grade_level, created_at, is_deleted)
        VALUES (:id, :tenant_id, :name, :description, :subject, 10, NOW(), false)
        ON CONFLICT DO NOTHING
    """), {
        "id": topic_id, "tenant_id": str(eff_tenant), "name": f"{subject} Topic",
        "description": f"CBSE {subject} questions", "subject": subject,
    })

    await db.execute(text("""
        INSERT INTO quizzes (id, tenant_id, topic_id, class_id, teacher_id, title, description,
                           total_questions, total_points, time_limit, is_active, created_at, is_deleted)
        VALUES (:id, :tenant_id, :topic_id, :class_id, :teacher_id, :title, :description,
                0, 0, :time_limit, true, NOW(), false)
    """), {
        "id": quiz_id, "tenant_id": str(eff_tenant), "topic_id": topic_id, "class_id": str(class_id),
        "teacher_id": str(eff_teacher), "title": title, "description": f"CBSE {subject} Quiz",
        "time_limit": time_limit,
    })

    await db.commit()
    return {"quiz_id": quiz_id, "topic_id": topic_id, "subject": subject, "title": title,
            "time_limit": time_limit, "status": "created"}


@router.post("/add-question/{quiz_id}")
async def add_question_to_quiz(
    quiz_id: UUID,
    request_data: dict,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),  # authoring: staff only
):
    """Add question to CBSE quiz"""
    question_text = request_data.get("question_text")
    question_type = request_data.get("question_type")
    correct_answer = request_data.get("correct_answer")
    points = request_data.get("points", 1)
    options = request_data.get("options")
    explanation = request_data.get("explanation")

    if options and isinstance(options, dict):
        options = json.dumps(options)

    if not question_text or not question_type or not correct_answer:
        raise HTTPException(status_code=400, detail="question_text, question_type, and correct_answer are required")

    question_id = str(uuid4())

    result = await db.execute(text("SELECT topic_id, tenant_id FROM quizzes WHERE id = :quiz_id"),
                              {"quiz_id": str(quiz_id)})
    quiz_data = result.fetchone()
    if not quiz_data:
        raise HTTPException(status_code=404, detail="Quiz not found")
    # The quiz must belong to the caller's tenant — no cross-tenant question injection.
    if not principal.is_super_admin and str(quiz_data[1]) != str(principal.tenant_id):
        raise HTTPException(status_code=403, detail="Quiz belongs to another school")

    await db.execute(text("""
        INSERT INTO questions (id, tenant_id, topic_id, question_text, question_type,
                             correct_answer, explanation, points, options, created_at, is_deleted)
        VALUES (:id, :tenant_id, :topic_id, :question_text, :question_type,
                :correct_answer, :explanation, :points, :options, NOW(), false)
    """), {
        "id": question_id, "tenant_id": quiz_data[1], "topic_id": quiz_data[0],
        "question_text": question_text, "question_type": question_type, "correct_answer": correct_answer,
        "explanation": explanation, "points": points, "options": options,
    })

    result = await db.execute(text("SELECT COUNT(*) FROM quiz_questions WHERE quiz_id = :quiz_id"),
                              {"quiz_id": str(quiz_id)})
    order_number = result.scalar() + 1

    await db.execute(text("""
        INSERT INTO quiz_questions (id, quiz_id, question_id, order_number, points, created_at, is_deleted)
        VALUES (:id, :quiz_id, :question_id, :order_number, :points, NOW(), false)
    """), {"id": str(uuid4()), "quiz_id": str(quiz_id), "question_id": question_id,
           "order_number": order_number, "points": points})

    await db.execute(text("""
        UPDATE quizzes SET
            total_questions = (SELECT COUNT(*) FROM quiz_questions WHERE quiz_id = :quiz_id),
            total_points = (SELECT SUM(points) FROM quiz_questions WHERE quiz_id = :quiz_id)
        WHERE id = :quiz_id
    """), {"quiz_id": str(quiz_id)})

    await db.commit()
    return {"question_id": question_id, "quiz_id": str(quiz_id), "order_number": order_number,
            "points": points, "status": "added"}


@router.get("/quiz/{quiz_id}")
async def get_quiz_details(
    quiz_id: UUID,
    include_answers: bool = False,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),  # students load quizzes to take them
):
    """Get quiz details with questions (tenant-scoped; answers only for staff)."""
    # Answer keys are staff-only no matter what the client asks for.
    show_answers = include_answers and (principal.is_super_admin or principal.is_staff)

    quiz_sql = """
        SELECT q.title, q.description, q.total_questions, q.total_points, q.time_limit,
               t.subject, t.name as topic_name
        FROM quizzes q
        JOIN topics t ON q.topic_id = t.id
        WHERE q.id = :quiz_id
    """
    params = {"quiz_id": str(quiz_id)}
    if not principal.is_super_admin:
        quiz_sql += " AND q.tenant_id = :tenant_id"
        params["tenant_id"] = str(principal.tenant_id)

    result = await db.execute(text(quiz_sql), params)
    quiz_info = result.fetchone()
    if not quiz_info:
        raise HTTPException(status_code=404, detail="Quiz not found")

    questions_query = "SELECT qz.order_number, q.id, q.question_text, q.question_type, q.options, qz.points"
    if show_answers:
        questions_query += ", q.correct_answer, q.explanation"
    questions_query += """
        FROM quiz_questions qz
        JOIN questions q ON qz.question_id = q.id
        WHERE qz.quiz_id = :quiz_id
        ORDER BY qz.order_number
    """

    result = await db.execute(text(questions_query), {"quiz_id": str(quiz_id)})
    questions = []
    for row in result.fetchall():
        question = {"order": row[0], "question_id": str(row[1]), "question_text": row[2],
                    "question_type": row[3], "options": row[4], "points": row[5]}
        if show_answers:
            question["correct_answer"] = row[6]
            question["explanation"] = row[7]
        questions.append(question)

    return {"quiz_id": str(quiz_id), "title": quiz_info[0], "description": quiz_info[1],
            "subject": quiz_info[5], "topic": quiz_info[6], "total_questions": quiz_info[2],
            "total_points": quiz_info[3], "time_limit": quiz_info[4], "questions": questions}


@router.post("/start-attempt/{quiz_id}")
async def start_quiz_attempt(
    quiz_id: UUID,
    request_data: dict,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),  # students start their own attempts
):
    """Start quiz attempt for the authenticated student"""
    # The attempt is always for the authenticated student in their own tenant.
    student_id = str(principal.user_id)
    tenant_id = principal.tenant_id
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="tenant context required")

    # The quiz must belong to the student's tenant.
    qrow = (await db.execute(
        text("SELECT total_points FROM quizzes WHERE id = :quiz_id AND tenant_id = :tenant_id AND is_deleted = false"),
        {"quiz_id": str(quiz_id), "tenant_id": str(tenant_id)},
    )).fetchone()
    if not qrow:
        raise HTTPException(status_code=404, detail="Quiz not found")
    max_score = qrow[0]

    attempt_id = str(uuid4())
    await db.execute(text("""
        INSERT INTO quiz_attempts (id, tenant_id, quiz_id, student_id, start_time,
                                 max_score, is_completed, is_submitted, created_at, is_deleted)
        VALUES (:id, :tenant_id, :quiz_id, :student_id, NOW(),
                :max_score, false, false, NOW(), false)
    """), {"id": attempt_id, "tenant_id": str(tenant_id), "quiz_id": str(quiz_id),
           "student_id": student_id, "max_score": max_score})

    await db.commit()
    return {"attempt_id": attempt_id, "quiz_id": str(quiz_id), "student_id": student_id,
            "start_time": datetime.now().isoformat(), "max_score": max_score, "status": "started"}


@router.post("/submit-answer")
async def submit_quiz_answer(
    request_data: dict,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),  # only the owning student writes
):
    """Submit answer for a quiz question (only for the caller's own attempt)."""
    attempt_id = request_data.get("attempt_id")
    question_id = request_data.get("question_id")
    student_answer = request_data.get("student_answer")
    time_taken = request_data.get("time_taken", 30)

    if not attempt_id or not question_id or not student_answer:
        raise HTTPException(status_code=400, detail="attempt_id, question_id, and student_answer required")

    # Ownership: the attempt must belong to the caller (no submitting on someone else's attempt).
    await _assert_attempt_access(db, principal, attempt_id, allow_staff=False)

    result = await db.execute(text("SELECT correct_answer, points FROM questions WHERE id = :question_id"),
                              {"question_id": str(question_id)})
    question_data = result.fetchone()
    if not question_data:
        raise HTTPException(status_code=404, detail="Question not found")

    correct_answer = question_data[0].strip().upper()
    student_answer_clean = student_answer.strip().upper()
    is_correct = student_answer_clean == correct_answer
    points_earned = question_data[1] if is_correct else 0

    await db.execute(text("""
        INSERT INTO quiz_answers (id, attempt_id, question_id, student_answer,
                                is_correct, points_earned, time_taken, created_at, is_deleted)
        VALUES (:id, :attempt_id, :question_id, :student_answer,
                :is_correct, :points_earned, :time_taken, NOW(), false)
    """), {"id": str(uuid4()), "attempt_id": str(attempt_id), "question_id": str(question_id),
           "student_answer": student_answer, "is_correct": is_correct,
           "points_earned": points_earned, "time_taken": time_taken})

    await db.commit()
    return {"attempt_id": str(attempt_id), "question_id": str(question_id), "student_answer": student_answer,
            "correct_answer": question_data[0], "is_correct": is_correct,
            "points_earned": points_earned, "status": "submitted"}


@router.post("/complete-attempt/{attempt_id}")
async def complete_quiz_attempt(
    attempt_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),  # only the owning student completes
):
    """Complete and calculate quiz attempt score (caller's own attempt)."""
    await _assert_attempt_access(db, principal, attempt_id, allow_staff=False)

    result = await db.execute(text("""
        SELECT SUM(points_earned), COUNT(*) FROM quiz_answers WHERE attempt_id = :attempt_id
    """), {"attempt_id": str(attempt_id)})
    score_data = result.fetchone()
    total_score = score_data[0] or 0
    answer_count = score_data[1] or 0

    result = await db.execute(text("SELECT qa.max_score FROM quiz_attempts qa WHERE qa.id = :attempt_id"),
                              {"attempt_id": str(attempt_id)})
    max_score = result.scalar()
    percentage = (total_score / max_score * 100) if max_score and max_score > 0 else 0

    await db.execute(text("""
        UPDATE quiz_attempts SET
            end_time = NOW(), total_score = :total_score, percentage = :percentage,
            is_completed = true, is_submitted = true
        WHERE id = :attempt_id
    """), {"attempt_id": str(attempt_id), "total_score": total_score, "percentage": percentage})

    await db.commit()
    return {"attempt_id": str(attempt_id), "total_score": total_score, "max_score": max_score,
            "percentage": round(percentage, 2), "answer_count": answer_count, "status": "completed"}


@router.get("/results/{attempt_id}")
async def get_quiz_results(
    attempt_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),  # owner student, or staff in tenant
):
    """Get detailed quiz results — only the owner student or a same-tenant staff member."""
    await _assert_attempt_access(db, principal, attempt_id, allow_staff=True)

    result = await db.execute(text("""
        SELECT qa.total_score, qa.max_score, qa.percentage, qa.start_time, qa.end_time,
               q.title, s.first_name, s.last_name
        FROM quiz_attempts qa
        JOIN quizzes q ON qa.quiz_id = q.id
        JOIN students s ON qa.student_id = s.id
        WHERE qa.id = :attempt_id
    """), {"attempt_id": str(attempt_id)})
    attempt_info = result.fetchone()
    if not attempt_info:
        raise HTTPException(status_code=404, detail="Quiz attempt not found")

    result = await db.execute(text("""
        SELECT qans.question_id, qans.student_answer, qans.is_correct, qans.points_earned,
               q.question_text, q.correct_answer, q.explanation
        FROM quiz_answers qans
        JOIN questions q ON qans.question_id = q.id
        WHERE qans.attempt_id = :attempt_id
        ORDER BY q.id
    """), {"attempt_id": str(attempt_id)})

    answers = [
        {"question_id": str(row[0]), "question_text": row[4], "student_answer": row[1],
         "correct_answer": row[5], "is_correct": row[2], "points_earned": row[3], "explanation": row[6]}
        for row in result.fetchall()
    ]

    return {"attempt_id": str(attempt_id), "quiz_title": attempt_info[5],
            "student_name": f"{attempt_info[6]} {attempt_info[7]}", "score": attempt_info[0],
            "max_score": attempt_info[1], "percentage": attempt_info[2],
            "start_time": attempt_info[3].isoformat() if attempt_info[3] else None,
            "end_time": attempt_info[4].isoformat() if attempt_info[4] else None, "answers": answers}
