# app/services/ai_quiz_service.py

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
import json

from ..models.tenant_specific.quiz import Topic, Question, Quiz, QuizAttempt, QuizAnswer
from ..schemas.ai_schemas import (
    QuestionGenerationRequest, QuestionGenerationResponse, GeneratedQuestion,
    QuizAssemblyRequest, QuizAssemblyResponse,
    SubjectiveGradingRequest, SubjectiveGradingResponse,
    PerformanceAnalysisRequest, PerformanceAnalysisResponse
)
from ..schemas.quiz_schemas import QuestionCreate, QuestionType
from .ai_service import AIService
from .quiz_service import QuizService

class AIQuizService:
    def __init__(self):
        self.ai_service = AIService()
        self.quiz_service = QuizService()
    
    async def generate_questions_ai(
        self, 
        db: AsyncSession, 
        request: QuestionGenerationRequest,
        tenant_id: UUID,
        auto_save: bool = False
    ) -> QuestionGenerationResponse:
        """Generate questions using AI and optionally save to database"""
        
        # Get topic details if topic_id is provided
        topic_name = None
        if hasattr(request, 'topic_id') and request.topic_id:
            topic_query = select(Topic).where(
                and_(Topic.id == request.topic_id, Topic.tenant_id == tenant_id)
            )
            topic_result = await db.execute(topic_query)
            topic = topic_result.scalar_one_or_none()
            if topic:
                topic_name = topic.name
        
        # Generate questions using AI
        generated_questions = await self.ai_service.generate_questions(
            topic=request.topic,
            subject=request.subject,
            grade_level=request.grade_level,
            question_type=request.question_type,
            difficulty=request.difficulty,
            count=request.count,
            learning_objectives=request.learning_objectives
        )
        
        questions = []
        saved_questions = []
        
        for q_data in generated_questions:
            question = GeneratedQuestion(**q_data)
            questions.append(question)
            
            if auto_save:
                # Save to database
                question_create = QuestionCreate(
                    topic_id=getattr(request, 'topic_id', None),
                    question_text=question.question_text,
                    question_type=request.question_type,
                    difficulty_level=request.difficulty,
                    options=question.options,
                    correct_answer=question.correct_answer,
                    explanation=question.explanation,
                    points=question.points,
                    original_source="AI Generated"
                )
                
                if hasattr(request, 'topic_id'):
                    saved_question = await self.quiz_service.create_question(
                        db, question_create, tenant_id
                    )
                    saved_questions.append(saved_question)
        
        # Prepare generation metadata
        generation_metadata = {
            "ai_model": "Perplexity",
            "generation_time": str(datetime.utcnow()),
            "auto_saved": auto_save,
            "saved_count": len(saved_questions),
            "learning_objectives": request.learning_objectives
        }
        
        return QuestionGenerationResponse(
            questions=questions,
            topic=request.topic,
            topic_name=topic_name,
            subject=request.subject,
            grade_level=request.grade_level,
            total_generated=len(questions),
            generation_metadata=generation_metadata
        )
    
    async def suggest_quiz_assembly_ai(
        self,
        db: AsyncSession,
        request: QuizAssemblyRequest,
        tenant_id: UUID
    ) -> QuizAssemblyResponse:
        """Get AI suggestions for optimal quiz assembly"""
        
        # Get available questions for the topic
        questions = await self.quiz_service.get_questions_by_topic(
            db, tenant_id, request.topic_id
        )
        
        # Prepare question data for AI
        available_questions = []
        for q in questions:
            available_questions.append({
                "id": str(q.id),
                "question_text": q.question_text[:100] + "...",  # Truncate for AI
                "question_type": q.question_type.value,
                "difficulty": q.difficulty_level.value,
                "points": q.points,
                "estimated_time": q.time_limit or 2  # Default 2 minutes
            })
        
        # Get AI suggestions
        suggestions = await self.ai_service.suggest_quiz_assembly(
            available_questions=available_questions,
            target_duration=request.target_duration,
            difficulty_distribution=request.difficulty_distribution
        )
        
        if not suggestions:
            # Fallback to simple selection
            selected_ids = [q["id"] for q in available_questions[:5]]
            # Get topic name for fallback
            topic_query = select(Topic).where(Topic.id == request.topic_id)
            topic_result = await db.execute(topic_query)
            topic = topic_result.scalar_one_or_none()
            topic_name = topic.name if topic else "Unknown Topic"
            quiz_title = f"{topic_name} - Basic Quiz"
            
            return QuizAssemblyResponse(
                selected_questions=[UUID(id) for id in selected_ids],
                suggested_order=[UUID(id) for id in selected_ids],
                time_per_question={id: 3 for id in selected_ids},
                difficulty_balance={"medium": len(selected_ids)},
                total_points=sum(q["points"] for q in available_questions[:5]),
                estimated_duration=15,
                recommendations="Basic question selection applied.",
                topic_name=topic_name,
                quiz_title=quiz_title
            )
        
        # Get topic name and generate quiz title suggestion
        topic_query = select(Topic).where(Topic.id == request.topic_id)
        topic_result = await db.execute(topic_query)
        topic = topic_result.scalar_one_or_none()
        topic_name = topic.name if topic else "Unknown Topic"
        
        # Generate quiz title suggestion
        quiz_title = f"{topic_name} - {topic.subject if topic else 'Quiz'} (Grade {topic.grade_level if topic else 'N/A'})"
        
        # Get question details with names for better display
        question_details = {}
        for q_id in suggestions.get("selected_questions", []):
            try:
                question_query = select(Question).options(selectinload(Question.topic)).where(Question.id == UUID(q_id))
                question_result = await db.execute(question_query)
                question = question_result.scalar_one_or_none()
                if question:
                    question_details[q_id] = {
                        "question_id": q_id,
                        "question_text": question.question_text[:100] + "...",
                        "topic_name": question.topic.name if question.topic else "Unknown",
                        "difficulty": str(question.difficulty_level),
                        "points": question.points
                    }
            except:
                continue
        
        return QuizAssemblyResponse(
            selected_questions=[UUID(id) for id in suggestions.get("selected_questions", [])],
            suggested_order=[UUID(id) for id in suggestions.get("suggested_order", [])],
            time_per_question=suggestions.get("time_per_question", {}),
            difficulty_balance=suggestions.get("difficulty_balance", {}),
            total_points=suggestions.get("total_points", 0),
            estimated_duration=suggestions.get("estimated_duration", 0),
            recommendations=suggestions.get("recommendations", ""),
            question_details=question_details,
            topic_name=topic_name,
            quiz_title=quiz_title
        )
    
    async def grade_subjective_answer_ai(
        self,
        request: SubjectiveGradingRequest
    ) -> SubjectiveGradingResponse:
        """Grade subjective answers using AI"""
        
        grading_result = await self.ai_service.grade_subjective_answer(
            question=request.question_text,
            correct_answer=request.correct_answer,
            student_answer=request.student_answer,
            max_points=request.max_points,
            rubric=request.rubric
        )
        
        if not grading_result:
            # Fallback grading
            return SubjectiveGradingResponse(
                points_earned=0,
                percentage=0.0,
                feedback="Unable to grade automatically. Manual review required.",
                strengths=[],
                improvements=["Requires manual grading"],
                is_correct=False
            )
        
        return SubjectiveGradingResponse(
            points_earned=grading_result.get("points_earned", 0),
            percentage=grading_result.get("percentage", 0.0),
            feedback=grading_result.get("feedback", ""),
            strengths=grading_result.get("strengths", []),
            improvements=grading_result.get("improvements", []),
            is_correct=grading_result.get("is_correct", False)
        )
    
    async def analyze_quiz_performance_ai(
        self,
        db: AsyncSession,
        request: PerformanceAnalysisRequest,
        tenant_id: UUID
    ) -> PerformanceAnalysisResponse:
        """Analyze quiz performance using AI"""
        
        # Get quiz attempts and results
        query = select(QuizAttempt).options(
            selectinload(QuizAttempt.quiz),
            selectinload(QuizAttempt.answers)
        ).where(
            and_(
                QuizAttempt.quiz_id == request.quiz_id,
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.is_submitted == True
            )
        )
        
        if request.class_id:
            # Add class filter if needed (would require student-class relationship)
            pass
        
        result = await db.execute(query)
        attempts = result.scalars().all()
        
        if not attempts:
            return PerformanceAnalysisResponse(
                overall_stats={},
                weak_areas=[],
                strong_areas=[],
                at_risk_students=[],
                top_performers=[],
                recommendations=["No data available for analysis"],
                question_analysis={},
                class_average=0.0,
                pass_rate=0.0
            )
        
        # Prepare data for AI analysis
        quiz_results = []
        for attempt in attempts:
            quiz_results.append({
                "student_id": str(attempt.student_id),
                "score": attempt.total_score,
                "max_score": attempt.max_score,
                "percentage": attempt.percentage,
                "time_taken": None,  # Would need to calculate from start/end time
                "answers": [
                    {
                        "question_id": str(answer.question_id),
                        "is_correct": answer.is_correct,
                        "points_earned": answer.points_earned
                    }
                    for answer in attempt.answers
                ]
            })
        
        class_info = {
            "quiz_id": str(request.quiz_id),
            "total_students": len(attempts),
            "quiz_title": attempts[0].quiz.title if attempts else "Unknown"
        }
        
        # Get AI analysis
        analysis = await self.ai_service.analyze_class_performance(
            quiz_results=quiz_results,
            class_info=class_info
        )
        
        if not analysis:
            # Fallback analysis
            scores = [attempt.percentage for attempt in attempts]
            avg_score = sum(scores) / len(scores) if scores else 0
            pass_rate = len([s for s in scores if s >= 60]) / len(scores) * 100 if scores else 0
            
            # Get quiz and topic names for fallback
            quiz_name = attempts[0].quiz.title if attempts else "Unknown Quiz"
            topic_name = None
            if attempts:
                quiz_query = select(Quiz).options(selectinload(Quiz.topic)).where(Quiz.id == request.quiz_id)
                quiz_result = await db.execute(quiz_query)
                quiz = quiz_result.scalar_one_or_none()
                if quiz and quiz.topic:
                    topic_name = quiz.topic.name
            
            return PerformanceAnalysisResponse(
                overall_stats={"average": avg_score, "total_students": len(attempts)},
                weak_areas=[],
                strong_areas=[],
                at_risk_students=[],
                top_performers=[],
                recommendations=["Basic analysis completed"],
                question_analysis={},
                class_average=avg_score,
                pass_rate=pass_rate,
                quiz_name=quiz_name,
                topic_name=topic_name
            )
        
        # Safely convert string UUIDs to UUID objects
        at_risk_students = []
        for student_id in analysis.get("at_risk_students", []):
            try:
                at_risk_students.append(UUID(student_id))
            except (ValueError, TypeError):
                continue
        
        top_performers = []
        for student_id in analysis.get("top_performers", []):
            try:
                top_performers.append(UUID(student_id))
            except (ValueError, TypeError):
                continue
        
        # Get student names for at-risk and top performers
        from ..models.tenant_specific.student import Student
        at_risk_with_names = []
        top_performers_with_names = []
        
        for student_id in at_risk_students:
            student_query = select(Student).where(Student.id == student_id)
            student_result = await db.execute(student_query)
            student = student_result.scalar_one_or_none()
            if student:
                at_risk_with_names.append({
                    "student_id": str(student_id),
                    "student_name": f"{student.first_name} {student.last_name}"
                })
        
        for student_id in top_performers:
            student_query = select(Student).where(Student.id == student_id)
            student_result = await db.execute(student_query)
            student = student_result.scalar_one_or_none()
            if student:
                top_performers_with_names.append({
                    "student_id": str(student_id),
                    "student_name": f"{student.first_name} {student.last_name}"
                })
        
        # Get quiz and topic names
        quiz_name = attempts[0].quiz.title if attempts else "Unknown Quiz"
        topic_name = None
        class_name = None
        
        if attempts:
            quiz_query = select(Quiz).options(selectinload(Quiz.topic)).where(Quiz.id == request.quiz_id)
            quiz_result = await db.execute(quiz_query)
            quiz = quiz_result.scalar_one_or_none()
            if quiz and quiz.topic:
                topic_name = quiz.topic.name
            
            # Get class name if class_id is provided
            if request.class_id:
                from ..models.tenant_specific.class_model import Class
                class_query = select(Class).where(Class.id == request.class_id)
                class_result = await db.execute(class_query)
                class_obj = class_result.scalar_one_or_none()
                if class_obj:
                    class_name = class_obj.name
        
        return PerformanceAnalysisResponse(
            overall_stats=analysis.get("overall_stats", {}),
            weak_areas=analysis.get("weak_areas", []),
            strong_areas=analysis.get("strong_areas", []),
            at_risk_students=at_risk_with_names,
            top_performers=top_performers_with_names,
            recommendations=analysis.get("recommendations", []),
            question_analysis=analysis.get("question_analysis", {}),
            class_average=analysis.get("overall_stats", {}).get("average_score", 0.0),
            pass_rate=analysis.get("overall_stats", {}).get("pass_rate", 0.0),
            quiz_name=quiz_name,
            class_name=class_name,
            topic_name=topic_name
        )
    
    async def enhance_quiz_grading(
        self,
        db: AsyncSession,
        attempt_id: UUID,
        tenant_id: UUID,
        use_ai_grading: bool = True
    ) -> Dict[str, Any]:
        """Enhanced quiz grading with AI for subjective questions"""
        
        # Get the quiz attempt
        attempt = await db.get(QuizAttempt, attempt_id)
        if not attempt:
            raise ValueError("Quiz attempt not found")
        
        # Get quiz with questions
        quiz_query = select(Quiz).options(
            selectinload(Quiz.quiz_questions).selectinload(QuizQuestion.question)
        ).where(Quiz.id == attempt.quiz_id)
        
        result = await db.execute(quiz_query)
        quiz = result.scalar_one_or_none()
        
        if not quiz:
            raise ValueError("Quiz not found")
        
        total_score = 0
        grading_details = []
        
        # Process each answer
        for quiz_question in quiz.quiz_questions:
            question = quiz_question.question
            
            # Find student's answer
            answer_query = select(QuizAnswer).where(
                and_(
                    QuizAnswer.attempt_id == attempt_id,
                    QuizAnswer.question_id == question.id
                )
            )
            answer_result = await db.execute(answer_query)
            student_answer = answer_result.scalar_one_or_none()
            
            if not student_answer:
                continue
            
            points_earned = 0
            feedback = ""
            
            # Use AI grading for subjective questions
            if (use_ai_grading and 
                question.question_type in [QuestionType.SHORT_ANSWER, QuestionType.ESSAY]):
                
                grading_request = SubjectiveGradingRequest(
                    question_text=question.question_text,
                    correct_answer=question.correct_answer,
                    student_answer=student_answer.student_answer,
                    max_points=question.points
                )
                
                ai_grading = await self.grade_subjective_answer_ai(grading_request)
                points_earned = ai_grading.points_earned
                feedback = ai_grading.feedback
                
                # Update answer with AI grading
                student_answer.points_earned = points_earned
                student_answer.is_correct = ai_grading.is_correct
                student_answer.ai_feedback = feedback
            else:
                # Use existing grading logic for objective questions
                is_correct = self.quiz_service._check_answer(question, student_answer.student_answer)
                points_earned = question.points if is_correct else 0
                student_answer.points_earned = points_earned
                student_answer.is_correct = is_correct
            
            total_score += points_earned
            
            grading_details.append({
                "question_id": str(question.id),
                "question_type": question.question_type.value,
                "points_possible": question.points,
                "points_earned": points_earned,
                "feedback": feedback
            })
        
        # Update attempt
        attempt.total_score = total_score
        attempt.percentage = int((total_score / attempt.max_score) * 100) if attempt.max_score > 0 else 0
        attempt.is_completed = True
        attempt.is_submitted = True
        
        await db.commit()
        
        return {
            "attempt_id": str(attempt_id),
            "total_score": total_score,
            "max_score": attempt.max_score,
            "percentage": attempt.percentage,
            "grading_details": grading_details,
            "ai_enhanced": use_ai_grading
        }