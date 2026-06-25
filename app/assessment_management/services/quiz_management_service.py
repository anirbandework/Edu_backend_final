# app/services/quiz_service.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from ..models.quiz_question_models import Topic, Question, Quiz, QuizQuestion, QuizAttempt, QuizAnswer, quiz_classes
from ..schemas.quiz_validation_schemas import (
    TopicCreate, QuestionCreate, QuizCreate, QuizAttemptStart, 
    QuizAnswerSubmit, QuizAttemptSubmit
)
from ...services.base_service import BaseService
from ...core.config_assessment import assessment_settings
import logging

logger = logging.getLogger(__name__)

class QuizService:
    
    # Topic methods
    async def create_topic(self, db: AsyncSession, topic_data: TopicCreate, tenant_id: UUID) -> Topic:
        topic = Topic(
            tenant_id=tenant_id,
            **topic_data.model_dump()
        )
        db.add(topic)
        await db.commit()
        await db.refresh(topic)
        return topic
    
    async def get_topics(self, db: AsyncSession, tenant_id: UUID, subject: Optional[str] = None, grade_level: Optional[int] = None) -> List[Topic]:
        query = select(Topic).where(
            and_(Topic.tenant_id == tenant_id, Topic.is_deleted == False)
        )
        
        if subject:
            query = query.where(Topic.subject == subject)
        if grade_level:
            query = query.where(Topic.grade_level == grade_level)
            
        result = await db.execute(query)
        return result.scalars().all()
    
    # Question methods
    async def create_question(self, db: AsyncSession, question_data: QuestionCreate, tenant_id: UUID) -> Question:
        # Extract fields that don't exist in the Question model
        question_dict = question_data.model_dump()
        category_ids = question_dict.pop('category_ids', None)
        
        question = Question(
            tenant_id=tenant_id,
            **question_dict
        )
        db.add(question)
        await db.flush()  # Get the question ID
        
        # Handle category associations if provided
        if category_ids:
            from ..models.quiz_question_models import Category
            for category_id in category_ids:
                # Verify category exists and belongs to tenant
                category = await db.get(Category, category_id)
                if category and category.tenant_id == tenant_id:
                    question.categories.append(category)
        
        await db.commit()
        await db.refresh(question)
        return question
    
    async def get_questions_by_topic(self, db: AsyncSession, tenant_id: UUID, topic_id: UUID) -> List[Question]:
        query = select(Question).where(
            and_(
                Question.tenant_id == tenant_id,
                Question.topic_id == topic_id,
                Question.is_deleted == False
            )
        )
        result = await db.execute(query)
        return result.scalars().all()
    
    # Quiz methods
    async def create_quiz(self, db: AsyncSession, quiz_data: QuizCreate, teacher_id: UUID, tenant_id: UUID) -> Quiz:
        # Calculate total points
        questions_query = select(Question).where(Question.id.in_(quiz_data.question_ids))
        questions_result = await db.execute(questions_query)
        questions = questions_result.scalars().all()
        
        total_points = sum(q.points for q in questions)
        
        quiz = Quiz(
            tenant_id=tenant_id,
            teacher_id=teacher_id,
            topic_id=quiz_data.topic_id,
            title=quiz_data.title,
            description=quiz_data.description,
            instructions=quiz_data.instructions,
            total_questions=len(quiz_data.question_ids),
            total_points=total_points,
            time_limit=quiz_data.time_limit,
            start_time=quiz_data.start_time,
            end_time=quiz_data.end_time,
            allow_retakes=quiz_data.allow_retakes,
            show_results_immediately=quiz_data.show_results_immediately
        )
        
        db.add(quiz)
        await db.flush()
        
        # Add class associations if provided
        if quiz_data.class_ids:
            for class_id in quiz_data.class_ids:
                # Insert directly into association table
                await db.execute(
                    quiz_classes.insert().values(
                        quiz_id=quiz.id,
                        class_id=class_id
                    )
                )
        
        # Add quiz questions
        for i, question_id in enumerate(quiz_data.question_ids):
            question = next(q for q in questions if q.id == question_id)
            quiz_question = QuizQuestion(
                quiz_id=quiz.id,
                question_id=question_id,
                order_number=i + 1,
                points=question.points
            )
            db.add(quiz_question)
        
        await db.commit()
        await db.refresh(quiz)
        return quiz
    
    async def get_quiz_for_student(self, db: AsyncSession, quiz_id: UUID, tenant_id: UUID):
        query = select(Quiz).options(
            selectinload(Quiz.quiz_questions).selectinload(QuizQuestion.question)
        ).where(
            and_(Quiz.id == quiz_id, Quiz.tenant_id == tenant_id, Quiz.is_deleted == False)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    # Quiz Attempt methods
    async def start_quiz_attempt(self, db: AsyncSession, student_id: UUID, quiz_id: UUID, tenant_id: UUID) -> QuizAttempt:
        # Check if student already has attempts
        existing_attempts = await db.execute(
            select(func.count(QuizAttempt.id)).where(
                and_(
                    QuizAttempt.student_id == student_id,
                    QuizAttempt.quiz_id == quiz_id,
                    QuizAttempt.tenant_id == tenant_id
                )
            )
        )
        attempt_count = existing_attempts.scalar() or 0
        
        # Get quiz to check max score
        quiz = await db.get(Quiz, quiz_id)
        
        attempt = QuizAttempt(
            tenant_id=tenant_id,
            quiz_id=quiz_id,
            student_id=student_id,
            attempt_number=attempt_count + 1,
            start_time=datetime.utcnow(),
            max_score=quiz.total_points
        )
        
        db.add(attempt)
        await db.commit()
        await db.refresh(attempt)
        return attempt
    
    async def submit_quiz_attempt(self, db: AsyncSession, attempt_data: QuizAttemptSubmit, tenant_id: UUID) -> QuizAttempt:
        attempt = await db.get(QuizAttempt, attempt_data.attempt_id)
        if not attempt:
            raise ValueError("Quiz attempt not found")
        
        total_score = 0
        
        # Process each answer
        for answer_data in attempt_data.answers:
            question = await db.get(Question, answer_data.question_id)
            
            # Auto-grade MCQ and T/F, manual grade short answers
            if question.question_type.value == "short_answer":
                points_earned = 0  # Will be graded manually
                is_correct = None  # Pending manual review
            else:
                is_correct = self._check_answer(question, answer_data.student_answer)
                points_earned = question.points if is_correct else 0
                total_score += points_earned
            
            quiz_answer = QuizAnswer(
                attempt_id=attempt.id,
                question_id=answer_data.question_id,
                student_answer=answer_data.student_answer,
                is_correct=is_correct,
                points_earned=points_earned
            )
            db.add(quiz_answer)
        
        # Update attempt
        attempt.end_time = datetime.utcnow()
        attempt.total_score = total_score
        attempt.percentage = int((total_score / attempt.max_score) * 100) if attempt.max_score > 0 else 0
        attempt.is_completed = True
        attempt.is_submitted = True
        
        await db.commit()
        await db.refresh(attempt)
        return attempt
    
    def _check_answer(self, question: Question, student_answer: str) -> bool:
        if question.question_type.value == "multiple_choice":
            return student_answer.strip().upper() == question.correct_answer.strip().upper()
        elif question.question_type.value == "true_false":
            return student_answer.strip().lower() == question.correct_answer.strip().lower()
        else:
            # Short answer requires manual grading
            return False
    
    async def get_student_available_quizzes(self, db: AsyncSession, student_id: UUID, tenant_id: UUID):
        try:
            # Simple approach: get all active quizzes for now
            query = select(Quiz).where(
                and_(
                    Quiz.tenant_id == tenant_id,
                    Quiz.is_active == True,
                    Quiz.is_deleted == False
                )
            ).order_by(Quiz.created_at.desc())
            
            result = await db.execute(query)
            quizzes = result.scalars().all()
            
            # Format response
            quiz_list = []
            for quiz in quizzes:
                quiz_list.append({
                    "id": quiz.id,
                    "title": quiz.title,
                    "description": quiz.description,
                    "total_questions": quiz.total_questions,
                    "total_points": quiz.total_points,
                    "time_limit": quiz.time_limit,
                    "is_active": quiz.is_active,
                    "created_at": quiz.created_at
                })
            
            return quiz_list
        except Exception as e:
            logger.error(f"Error in get_student_available_quizzes: {e}")
            return []
    
    async def get_teacher_quizzes(self, db: AsyncSession, teacher_id: UUID, tenant_id: UUID):
        """Get all quizzes created by a teacher."""
        query = select(Quiz).where(
            and_(
                Quiz.teacher_id == teacher_id,
                Quiz.tenant_id == tenant_id,
                Quiz.is_deleted == False
            )
        ).order_by(Quiz.created_at.desc())
        
        result = await db.execute(query)
        quizzes = result.scalars().all()
        
        # Get attempt counts for each quiz
        quiz_list = []
        for quiz in quizzes:
            attempt_count = await db.execute(
                select(func.count(QuizAttempt.id)).where(
                    and_(
                        QuizAttempt.quiz_id == quiz.id,
                        QuizAttempt.is_submitted == True
                    )
                )
            )
            count = attempt_count.scalar() or 0
            
            quiz_list.append({
                "id": quiz.id,
                "title": quiz.title,
                "description": quiz.description,
                "total_questions": quiz.total_questions,
                "total_points": quiz.total_points,
                "time_limit": quiz.time_limit,
                "is_active": quiz.is_active,
                "created_at": quiz.created_at,
                "submitted_attempts": count
            })
        
        return quiz_list
    
    async def get_quiz_results(self, db: AsyncSession, quiz_id: UUID, teacher_id: UUID, tenant_id: UUID):
        # Verify quiz belongs to teacher
        quiz = await db.execute(
            select(Quiz).where(
                and_(
                    Quiz.id == quiz_id,
                    Quiz.teacher_id == teacher_id,
                    Quiz.tenant_id == tenant_id
                )
            )
        )
        quiz_obj = quiz.scalar_one_or_none()
        
        if not quiz_obj:
            return None
        
        # Get all attempts for this quiz with student info
        from sqlalchemy import text
        results_query = text("""
            SELECT 
                qa.id as attempt_id,
                qa.student_id,
                s.first_name,
                s.last_name,
                qa.attempt_number,
                qa.total_score,
                qa.max_score,
                qa.percentage,
                qa.start_time,
                qa.end_time,
                qa.is_completed,
                qa.is_submitted
            FROM quiz_attempts qa
            JOIN students s ON qa.student_id = s.id
            WHERE qa.quiz_id = :quiz_id 
            AND qa.tenant_id = :tenant_id
            AND qa.is_submitted = true
            ORDER BY qa.created_at DESC
        """)
        
        result = await db.execute(results_query, {"quiz_id": quiz_id, "tenant_id": tenant_id})
        attempts = result.fetchall()
        
        return {
            "quiz_id": quiz_id,
            "quiz_title": quiz_obj.title,
            "total_attempts": len(attempts),
            "attempts": [
                {
                    "attempt_id": attempt[0],
                    "student_id": attempt[1],
                    "student_name": f"{attempt[2]} {attempt[3]}",
                    "attempt_number": attempt[4],
                    "total_score": attempt[5],
                    "max_score": attempt[6],
                    "percentage": attempt[7],
                    "start_time": attempt[8],
                    "end_time": attempt[9],
                    "is_completed": attempt[10],
                    "is_submitted": attempt[11]
                } for attempt in attempts
            ]
        }
    
    async def delete_quiz(self, db: AsyncSession, quiz_id: UUID, teacher_id: UUID, tenant_id: UUID) -> bool:
        # Verify quiz belongs to teacher
        quiz = await db.execute(
            select(Quiz).where(
                and_(
                    Quiz.id == quiz_id,
                    Quiz.teacher_id == teacher_id,
                    Quiz.tenant_id == tenant_id
                )
            )
        )
        quiz_obj = quiz.scalar_one_or_none()
        
        if not quiz_obj:
            return False
        
        # Soft delete
        quiz_obj.is_deleted = True
        await db.commit()
        return True
    
    async def get_student_quiz_results(self, db: AsyncSession, student_id: UUID, tenant_id: UUID) -> List[QuizAttempt]:
        query = select(QuizAttempt).options(
            selectinload(QuizAttempt.quiz).selectinload(Quiz.topic)
        ).where(
            and_(
                QuizAttempt.student_id == student_id,
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.is_submitted == True,
                QuizAttempt.results_published == True  # Only show published results
            )
        ).order_by(QuizAttempt.created_at.desc())
        
        result = await db.execute(query)
        return result.scalars().all()
    
    async def update_quiz_status(self, db: AsyncSession, quiz_id: UUID, teacher_id: UUID, tenant_id: UUID, is_active: bool) -> bool:
        """Update quiz active status. Returns True if successful, False if quiz not found or unauthorized."""
        quiz = await db.execute(
            select(Quiz).where(
                and_(
                    Quiz.id == quiz_id,
                    Quiz.teacher_id == teacher_id,
                    Quiz.tenant_id == tenant_id,
                    Quiz.is_deleted == False
                )
            )
        )
        quiz_obj = quiz.scalar_one_or_none()
        
        if not quiz_obj:
            return False
        
        quiz_obj.is_active = is_active
        await db.commit()
        return True
    
    async def get_pending_grading(self, db: AsyncSession, teacher_id: UUID, tenant_id: UUID):
        """Get all short answer questions pending manual grading for teacher's quizzes."""
        from sqlalchemy import text
        
        try:
            query = text("""
                SELECT 
                    qa.id,
                    qa.attempt_id,
                    qa.question_id,
                    qa.student_answer,
                    q.question_text,
                    q.points,
                    s.first_name,
                    s.last_name,
                    quiz.title,
                    qz_att.student_id
                FROM quiz_answers qa
                JOIN questions q ON qa.question_id = q.id
                JOIN quiz_attempts qz_att ON qa.attempt_id = qz_att.id
                JOIN quizzes quiz ON qz_att.quiz_id = quiz.id
                JOIN students s ON qz_att.student_id = s.id
                WHERE quiz.teacher_id = :teacher_id 
                AND quiz.tenant_id = :tenant_id
                AND q.question_type = 'short_answer'
                AND qa.is_correct IS NULL
                ORDER BY qz_att.created_at DESC
            """)
            
            result = await db.execute(query, {"teacher_id": teacher_id, "tenant_id": tenant_id})
            rows = result.fetchall()
            
            return [
                {
                    "answer_id": str(row[0]),
                    "attempt_id": str(row[1]),
                    "question_id": str(row[2]),
                    "student_answer": row[3] or "",
                    "question_text": row[4] or "",
                    "max_points": int(row[5]) if row[5] else 0,
                    "first_name": row[6] or "",
                    "last_name": row[7] or "",
                    "quiz_title": row[8] or "",
                    "student_id": str(row[9])
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Error in get_pending_grading: {e}")
            return []
    
    async def grade_short_answer(self, db: AsyncSession, answer_id: UUID, points_awarded: int, teacher_id: UUID, tenant_id: UUID) -> bool:
        """Grade a short answer question and update total score."""
        # Get the answer and verify teacher owns the quiz
        from sqlalchemy import text
        verify_query = text("""
            SELECT qa.*, q.points as max_points, qz_att.id as attempt_id
            FROM quiz_answers qa
            JOIN questions q ON qa.question_id = q.id
            JOIN quiz_attempts qz_att ON qa.attempt_id = qz_att.id
            JOIN quizzes quiz ON qz_att.quiz_id = quiz.id
            WHERE qa.id = :answer_id 
            AND quiz.teacher_id = :teacher_id
            AND quiz.tenant_id = :tenant_id
        """)
        
        result = await db.execute(verify_query, {
            "answer_id": answer_id,
            "teacher_id": teacher_id, 
            "tenant_id": tenant_id
        })
        answer_data = result.fetchone()
        
        if not answer_data:
            return False
        
        # Update the answer with manual grade
        update_answer = text("""
            UPDATE quiz_answers 
            SET points_earned = :points_awarded,
                is_correct = CASE WHEN :points_awarded > 0 THEN true ELSE false END
            WHERE id = :answer_id
        """)
        
        await db.execute(update_answer, {
            "answer_id": answer_id,
            "points_awarded": min(points_awarded, answer_data.max_points)
        })
        
        # Recalculate total score for the attempt
        recalc_query = text("""
            UPDATE quiz_attempts 
            SET total_score = (
                SELECT COALESCE(SUM(points_earned), 0) 
                FROM quiz_answers 
                WHERE attempt_id = :attempt_id
            ),
            percentage = (
                SELECT CASE WHEN max_score > 0 THEN 
                    ROUND((COALESCE(SUM(points_earned), 0) * 100.0) / max_score)
                ELSE 0 END
                FROM quiz_answers 
                WHERE attempt_id = :attempt_id
            )
            WHERE id = :attempt_id
        """)
        
        await db.execute(recalc_query, {"attempt_id": answer_data.attempt_id})
        await db.commit()
        return True
    
    async def get_attempts_ready_for_publishing(self, db: AsyncSession, teacher_id: UUID, tenant_id: UUID):
        """Get quiz attempts that are fully graded and ready for result publishing."""
        from sqlalchemy import text
        
        try:
            query = text("""
                SELECT DISTINCT
                    qa.id,
                    qa.quiz_id,
                    qa.student_id,
                    s.first_name,
                    s.last_name,
                    quiz.title,
                    qa.total_score,
                    qa.max_score,
                    qa.percentage,
                    qa.results_published
                FROM quiz_attempts qa
                JOIN quizzes quiz ON qa.quiz_id = quiz.id
                JOIN students s ON qa.student_id = s.id
                WHERE quiz.teacher_id = :teacher_id 
                AND quiz.tenant_id = :tenant_id
                AND qa.is_submitted = true
                AND NOT EXISTS (
                    SELECT 1 FROM quiz_answers qans
                    JOIN questions q ON qans.question_id = q.id
                    WHERE qans.attempt_id = qa.id
                    AND q.question_type = 'short_answer'
                    AND qans.is_correct IS NULL
                )
                ORDER BY qa.created_at DESC
            """)
            
            result = await db.execute(query, {"teacher_id": teacher_id, "tenant_id": tenant_id})
            rows = result.fetchall()
            
            return [
                {
                    "attempt_id": str(row[0]),
                    "quiz_id": str(row[1]),
                    "student_id": str(row[2]),
                    "student_name": f"{row[3]} {row[4]}",
                    "quiz_title": row[5] or "",
                    "total_score": int(row[6]) if row[6] else 0,
                    "max_score": int(row[7]) if row[7] else 0,
                    "percentage": int(row[8]) if row[8] else 0,
                    "results_published": bool(row[9]) if row[9] is not None else False
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Error in get_attempts_ready_for_publishing: {e}")
            return []
    
    async def publish_quiz_results(self, db: AsyncSession, attempt_ids: List[UUID], teacher_id: UUID, tenant_id: UUID) -> bool:
        """Publish results for completed quiz attempts."""
        try:
            if not attempt_ids:
                return False
            
            # Convert UUIDs to strings for SQL
            attempt_id_strs = [str(aid) for aid in attempt_ids]
            
            # Verify all attempts belong to teacher's quizzes
            for attempt_id in attempt_ids:
                verify_query = select(QuizAttempt).join(Quiz).where(
                    and_(
                        QuizAttempt.id == attempt_id,
                        Quiz.teacher_id == teacher_id,
                        Quiz.tenant_id == tenant_id
                    )
                )
                result = await db.execute(verify_query)
                if not result.scalar_one_or_none():
                    return False
            
            # Update attempts to published
            for attempt_id in attempt_ids:
                update_query = select(QuizAttempt).where(QuizAttempt.id == attempt_id)
                result = await db.execute(update_query)
                attempt = result.scalar_one_or_none()
                if attempt:
                    attempt.results_published = True
            
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error in publish_quiz_results: {e}")
            await db.rollback()
            return False
    
    async def create_quiz_with_questions(self, db: AsyncSession, quiz_data: 'QuizCreateWithQuestions', teacher_id: UUID, tenant_id: UUID) -> Quiz:
        """Create a quiz with inline questions without requiring pre-existing topics."""
        # Create a default topic for this quiz
        topic = Topic(
            tenant_id=tenant_id,
            name=f"{quiz_data.title} - Topic",
            description=f"Auto-generated topic for {quiz_data.title}",
            subject=quiz_data.subject,
            grade_level=quiz_data.grade_level or 1
        )
        db.add(topic)
        await db.flush()
        
        # Create questions
        question_ids = []
        total_points = 0
        
        for q_data in quiz_data.questions:
            question = Question(
                tenant_id=tenant_id,
                topic_id=topic.id,
                question_text=q_data.question_text,
                question_type=q_data.question_type,
                difficulty_level=q_data.difficulty_level,
                options=q_data.options,
                correct_answer=q_data.correct_answer,
                explanation=q_data.explanation,
                points=q_data.points
            )
            db.add(question)
            await db.flush()
            question_ids.append(question.id)
            total_points += q_data.points
        
        # Create quiz
        quiz = Quiz(
            tenant_id=tenant_id,
            teacher_id=teacher_id,
            topic_id=topic.id,
            title=quiz_data.title,
            description=quiz_data.description,
            instructions=quiz_data.instructions,
            total_questions=len(quiz_data.questions),
            total_points=total_points,
            time_limit=quiz_data.time_limit,
            start_time=quiz_data.start_time,
            end_time=quiz_data.end_time,
            allow_retakes=quiz_data.allow_retakes,
            show_results_immediately=quiz_data.show_results_immediately
        )
        
        db.add(quiz)
        await db.flush()
        
        # Add class associations
        if quiz_data.class_ids:
            for class_id in quiz_data.class_ids:
                await db.execute(
                    quiz_classes.insert().values(
                        quiz_id=quiz.id,
                        class_id=class_id
                    )
                )
        
        # Add quiz questions
        for i, question_id in enumerate(question_ids):
            quiz_question = QuizQuestion(
                quiz_id=quiz.id,
                question_id=question_id,
                order_number=i + 1,
                points=quiz_data.questions[i].points
            )
            db.add(quiz_question)
        
        await db.commit()
        await db.refresh(quiz)
        return quiz