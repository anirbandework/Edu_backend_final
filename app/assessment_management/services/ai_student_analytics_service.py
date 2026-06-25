# app/services/ai_learning_service.py

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from uuid import UUID
import json
from datetime import datetime, timedelta, date

from ..models.quiz_question_models import Quiz, QuizAttempt, QuizAnswer, Question, Topic
from ..schemas.ai_analytics_schemas import (
    StudentInsightsRequest, StudentInsightsResponse,
    StudyRecommendationRequest, StudyRecommendationResponse,
    WeaknessAnalysisRequest, WeaknessAnalysisResponse,
    ExamPrepRequest, ExamPrepResponse,
    PerformancePredictionRequest, PerformancePredictionResponse
)
from .ai_integration_service import AIService

import logging
logger = logging.getLogger(__name__)

class AILearningService:
    def __init__(self):
        self.ai_service = AIService()
    
    async def analyze_student_insights(
        self,
        db: AsyncSession,
        request: StudentInsightsRequest,
        tenant_id: UUID
    ) -> StudentInsightsResponse:
        """Analyze student performance and provide personalized insights"""
        
        # Get student's quiz attempts with answers using raw SQL to avoid enum issues
        from sqlalchemy import text
        
        # First get basic attempt data
        query = select(QuizAttempt).options(
            selectinload(QuizAttempt.quiz).selectinload(Quiz.topic)
        ).where(
            and_(
                QuizAttempt.student_id == request.student_id,
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.is_submitted == True
            )
        ).order_by(desc(QuizAttempt.created_at))
        
        if request.subject:
            # Filter by subject if provided
            query = query.join(Quiz).join(Topic).where(Topic.subject == request.subject)
        
        result = await db.execute(query)
        attempts = result.scalars().all()
        
        # Get student name
        from ...student_management.models.student import Student
        student_query = select(Student).where(Student.id == request.student_id)
        student_result = await db.execute(student_query)
        student = student_result.scalar_one_or_none()
        student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
        
        if not attempts:
            return StudentInsightsResponse(
                student_id=request.student_id,
                student_name=student_name,
                overall_performance={},
                subject_breakdown={},
                learning_trends=[],
                strengths=[],
                weaknesses=[],
                recommendations=[],
                progress_score=0.0
            )
        
        # Get detailed answer analysis using raw SQL to avoid enum issues
        from sqlalchemy import text
        
        answer_query = text("""
            SELECT qa.attempt_id, qa.question_id, qa.is_correct, qa.points_earned,
                   q.question_text, q.points as max_points, t.name as topic_name
            FROM quiz_answers qa
            JOIN questions q ON qa.question_id = q.id
            JOIN topics t ON q.topic_id = t.id
            WHERE qa.attempt_id = ANY(:attempt_ids)
            ORDER BY qa.attempt_id, qa.question_id
        """)
        
        attempt_ids = [str(attempt.id) for attempt in attempts]
        answer_result = await db.execute(answer_query, {"attempt_ids": attempt_ids})
        answers_data = answer_result.fetchall()
        
        # Analyze topic-wise performance
        topic_performance = {}
        for answer in answers_data:
            topic = answer.topic_name
            if topic not in topic_performance:
                topic_performance[topic] = {"correct": 0, "total": 0, "points_earned": 0, "max_points": 0}
            
            topic_performance[topic]["total"] += 1
            topic_performance[topic]["max_points"] += answer.max_points
            topic_performance[topic]["points_earned"] += answer.points_earned or 0
            if answer.is_correct:
                topic_performance[topic]["correct"] += 1
        
        # Calculate topic percentages and identify strengths/weaknesses
        topic_analysis = {}
        strong_topics = []
        weak_topics = []
        
        for topic, perf in topic_performance.items():
            if perf["total"] > 0:
                percentage = (perf["correct"] / perf["total"]) * 100
                topic_analysis[topic] = {
                    "percentage": percentage,
                    "correct": perf["correct"],
                    "total": perf["total"]
                }
                
                if percentage >= 60:
                    strong_topics.append(f"{topic} ({percentage:.1f}%)")
                elif percentage <= 30:
                    weak_topics.append(f"{topic} ({percentage:.1f}%)")
        
        subject_topics = set(topic_performance.keys())
        
        # Analyze actual performance data
        scores = [attempt.percentage for attempt in attempts]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        # Determine performance level and trends
        recent_scores = scores[-3:] if len(scores) >= 3 else scores
        trend = "stable"
        if len(scores) >= 3:
            if recent_scores[-1] > recent_scores[0]:
                trend = "improving"
            elif recent_scores[-1] < recent_scores[0]:
                trend = "declining"
        
        # Performance-based analysis
        if avg_score < 30:
            performance_level = "needs_significant_improvement"
            base_strengths = ["Shows persistence by attempting multiple quizzes"]
            if strong_topics:
                base_strengths.extend([f"Relatively better performance in: {', '.join(strong_topics)}"]) 
            strengths = base_strengths
            
            base_weaknesses = ["Very low quiz scores indicate fundamental knowledge gaps"]
            if weak_topics:
                base_weaknesses.extend([f"Significant struggles in: {', '.join(weak_topics)}"]) 
            base_weaknesses.extend([
                "May need to review basic concepts before attempting advanced problems",
                "Possible issues with question comprehension or time management"
            ])
            weaknesses = base_weaknesses
            base_recommendations = ["Start with foundational concepts review"]
            if weak_topics:
                base_recommendations.append(f"Focus intensive practice on: {', '.join([t.split(' (')[0] for t in weak_topics])}")
            base_recommendations.extend([
                "Work with a tutor or teacher for personalized guidance",
                "Practice basic problems before attempting quiz-level questions",
                "Review incorrect answers to understand mistake patterns"
            ])
            recommendations = base_recommendations
        elif avg_score < 50:
            performance_level = "below_average"
            base_strengths = ["Regular participation", "Some correct answers show partial understanding"]
            if strong_topics:
                base_strengths.append(f"Good performance in: {', '.join(strong_topics)}")
            strengths = base_strengths
            
            base_weaknesses = ["Below average performance"]
            if weak_topics:
                base_weaknesses.append(f"Needs improvement in: {', '.join(weak_topics)}")
            base_weaknesses.append("Key concept gaps identified")
            weaknesses = base_weaknesses
            
            base_recommendations = ["Focus on weak topics", "Increase practice time"]
            if weak_topics:
                base_recommendations.append(f"Extra practice needed in: {', '.join([t.split(' (')[0] for t in weak_topics])}")
            base_recommendations.append("Seek additional help")
            recommendations = base_recommendations
        elif avg_score < 70:
            performance_level = "average"
            base_strengths = ["Consistent participation", "Average performance level"]
            if strong_topics:
                base_strengths.append(f"Strong areas: {', '.join(strong_topics)}")
            strengths = base_strengths
            
            base_weaknesses = ["Room for improvement in accuracy"]
            if weak_topics:
                base_weaknesses.append(f"Weaker areas: {', '.join(weak_topics)}")
            weaknesses = base_weaknesses
            
            base_recommendations = ["Target specific weak areas", "Regular practice sessions"]
            if weak_topics:
                base_recommendations.append(f"Focus practice on: {', '.join([t.split(' (')[0] for t in weak_topics])}")
            recommendations = base_recommendations
        else:
            performance_level = "good"
            base_strengths = ["Good performance", "Strong understanding"]
            if strong_topics:
                base_strengths.append(f"Excellent in: {', '.join(strong_topics)}")
            strengths = base_strengths
            
            base_weaknesses = ["Minor areas for refinement"]
            if weak_topics:
                base_weaknesses.append(f"Could improve: {', '.join(weak_topics)}")
            weaknesses = base_weaknesses
            
            base_recommendations = ["Continue current approach"]
            if weak_topics:
                base_recommendations.append(f"Polish skills in: {', '.join([t.split(' (')[0] for t in weak_topics])}")
            base_recommendations.append("Challenge with advanced problems")
            recommendations = base_recommendations
        
        # Topic analysis already done above
        
        learning_trends = [
            f"Performance trend: {trend} (average: {avg_score:.1f}%)",
            f"Completed {len(attempts)} quizzes across {len(subject_topics)} topics"
        ]
        
        if avg_score < 30:
            learning_trends.append("Scores indicate need for foundational review")
        
        # Get topic names for better display
        topic_names = {}
        for topic_id in subject_topics:
            topic_query = select(Topic).where(Topic.name == topic_id)
            topic_result = await db.execute(topic_query)
            topic = topic_result.scalar_one_or_none()
            if topic:
                topic_names[topic_id] = topic.name
        
        # Enhanced topic analysis with names
        enhanced_topic_analysis = {}
        for topic, data in topic_analysis.items():
            enhanced_topic_analysis[topic] = {
                **data,
                "topic_name": topic_names.get(topic, topic)
            }
        
        return StudentInsightsResponse(
            student_id=request.student_id,
            student_name=student_name,
            overall_performance={
                "average_score": avg_score,
                "total_quizzes": len(attempts),
                "performance_level": performance_level,
                "trend": trend
            },
            subject_breakdown={
                "Mathematics": {
                    "average": avg_score,
                    "quiz_count": len(attempts),
                    "topics_covered": len(subject_topics),
                    "performance_level": performance_level,
                    "topic_analysis": enhanced_topic_analysis
                }
            },
            learning_trends=learning_trends,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
            progress_score=min(avg_score / 10, 10.0)
        )
        
        # Temporarily disabled due to enum mismatch - using fallback above
        
        prompt = f"""
Analyze this student's learning performance and provide detailed insights:

Student Performance Data: {json.dumps(performance_data, indent=2)}
Analysis Period: {request.time_period or 'All time'}

Provide comprehensive analysis including:
1. Overall performance trends
2. Subject-wise breakdown
3. Learning patterns and trends
4. Key strengths and areas of excellence
5. Specific weaknesses and knowledge gaps
6. Personalized learning recommendations
7. Progress trajectory and improvement areas

Format as JSON:
{{
  "overall_performance": {{
    "average_score": 75.5,
    "improvement_trend": "improving/declining/stable",
    "consistency_rating": "high/medium/low",
    "total_quizzes": 10
  }},
  "subject_breakdown": {{
    "Mathematics": {{"average": 80, "trend": "improving", "quiz_count": 5}},
    "Science": {{"average": 70, "trend": "stable", "quiz_count": 3}}
  }},
  "learning_trends": [
    "Shows consistent improvement in problem-solving",
    "Performance varies significantly across topics"
  ],
  "strengths": [
    "Excellent in algebraic concepts",
    "Strong analytical thinking"
  ],
  "weaknesses": [
    "Struggles with geometry problems",
    "Time management in complex questions"
  ],
  "recommendations": [
    "Focus on geometry practice with visual aids",
    "Practice timed problem-solving sessions"
  ],
  "progress_score": 7.5
}}
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.ai_service._make_request(messages)
        
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                analysis = json.loads(json_str)
                
                return StudentInsightsResponse(
                    student_id=request.student_id,
                    overall_performance=analysis.get("overall_performance", {}),
                    subject_breakdown=analysis.get("subject_breakdown", {}),
                    learning_trends=analysis.get("learning_trends", []),
                    strengths=analysis.get("strengths", []),
                    weaknesses=analysis.get("weaknesses", []),
                    recommendations=analysis.get("recommendations", []),
                    progress_score=analysis.get("progress_score", 0.0)
                )
        except Exception as e:
            logger.error(f"AI analysis parsing error: {e}")
        
        # Fallback analysis
        scores = [attempt.percentage for attempt in attempts]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        return StudentInsightsResponse(
            student_id=request.student_id,
            overall_performance={"average_score": avg_score, "total_quizzes": len(attempts)},
            subject_breakdown={},
            learning_trends=["Analysis completed with basic metrics"],
            strengths=["Consistent participation"],
            weaknesses=["Requires detailed analysis"],
            recommendations=["Continue regular practice"],
            progress_score=avg_score / 10
        )
    
    async def generate_study_recommendations(
        self,
        db: AsyncSession,
        request: StudyRecommendationRequest,
        tenant_id: UUID
    ) -> StudyRecommendationResponse:
        """Generate personalized study recommendations"""
        
        # Get student's recent performance (avoiding answers to prevent enum issues)
        query = select(QuizAttempt).options(
            selectinload(QuizAttempt.quiz).selectinload(Quiz.topic)
        ).where(
            and_(
                QuizAttempt.student_id == request.student_id,
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.is_submitted == True
            )
        ).order_by(desc(QuizAttempt.created_at)).limit(10)
        
        result = await db.execute(query)
        recent_attempts = result.scalars().all()
        
        # Analyze weak topics based on quiz performance
        topic_performance = {}
        for attempt in recent_attempts:
            topic_name = attempt.quiz.topic.name if attempt.quiz.topic else "General"
            if topic_name not in topic_performance:
                topic_performance[topic_name] = {"scores": [], "total_attempts": 0}
            
            topic_performance[topic_name]["scores"].append(attempt.percentage)
            topic_performance[topic_name]["total_attempts"] += 1
        
        # Calculate averages for weak topic identification
        for topic, data in topic_performance.items():
            if data["scores"]:
                data["average_score"] = sum(data["scores"]) / len(data["scores"])
                data["correct"] = len([s for s in data["scores"] if s >= 60])  # Assuming 60% is passing
                data["total"] = len(data["scores"])
        
        prompt = f"""
Generate personalized study recommendations for this student:

Student ID: {request.student_id}
Target Subject: {request.subject or 'All subjects'}
Study Goals: {request.study_goals or 'General improvement'}
Available Study Time: {request.available_time_hours or 'Not specified'} hours per week

Topic Performance Analysis: {json.dumps(topic_performance, indent=2)}

Provide detailed study plan including:
1. Priority topics to focus on
2. Specific study activities and resources
3. Time allocation recommendations
4. Practice question suggestions
5. Study schedule template
6. Progress milestones

Format as JSON:
{{
  "priority_topics": [
    {{
      "topic": "Algebra",
      "priority_level": "high",
      "current_score": 65,
      "target_score": 85,
      "estimated_hours": 8
    }}
  ],
  "study_activities": [
    {{
      "activity": "Practice linear equations",
      "duration": "30 minutes daily",
      "resources": ["Khan Academy", "Textbook Chapter 5"],
      "difficulty": "medium"
    }}
  ],
  "weekly_schedule": {{
    "Monday": ["Algebra practice - 1 hour", "Review mistakes - 30 min"],
    "Tuesday": ["Geometry concepts - 45 min"]
  }},
  "practice_recommendations": [
    "Solve 10 algebra problems daily",
    "Take weekly practice quizzes"
  ],
  "milestones": [
    {{
      "week": 1,
      "goal": "Complete basic algebra review",
      "success_criteria": "Score 80%+ on practice quiz"
    }}
  ],
  "estimated_improvement": "15-20% score increase in 4 weeks"
}}
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.ai_service._make_request(messages)
        
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                recommendations = json.loads(json_str)
                
                # Get student name
                from ...student_management.models.student import Student
                student_query = select(Student).where(Student.id == request.student_id)
                student_result = await db.execute(student_query)
                student = student_result.scalar_one_or_none()
                student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
                
                return StudyRecommendationResponse(
                    student_id=request.student_id,
                    student_name=student_name,
                    priority_topics=recommendations.get("priority_topics", []),
                    study_activities=recommendations.get("study_activities", []),
                    weekly_schedule=recommendations.get("weekly_schedule", {}),
                    practice_recommendations=recommendations.get("practice_recommendations", []),
                    milestones=recommendations.get("milestones", []),
                    estimated_improvement=recommendations.get("estimated_improvement", "")
                )
        except Exception as e:
            logger.error(f"Study recommendations parsing error: {e}")
        
        # Fallback recommendations
        weak_topics = [topic for topic, perf in topic_performance.items() 
                      if perf.get("total", 0) > 0 and (perf.get("correct", 0) / perf["total"]) < 0.7]
        
        # Get student name
        from ...student_management.models.student import Student
        student_query = select(Student).where(Student.id == request.student_id)
        student_result = await db.execute(student_query)
        student = student_result.scalar_one_or_none()
        student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
        
        return StudyRecommendationResponse(
            student_id=request.student_id,
            student_name=student_name,
            priority_topics=[{"topic": topic, "priority_level": "medium"} for topic in weak_topics[:3]],
            study_activities=[{"activity": "Review and practice", "duration": "30 minutes daily"}],
            weekly_schedule={"Daily": ["Practice weak topics - 30 minutes"]},
            practice_recommendations=["Focus on identified weak areas"],
            milestones=[{"week": 1, "goal": "Improve weak topic scores"}],
            estimated_improvement="Gradual improvement expected with consistent practice"
        )
    
    async def identify_knowledge_gaps(
        self,
        db: AsyncSession,
        request: WeaknessAnalysisRequest,
        tenant_id: UUID
    ) -> WeaknessAnalysisResponse:
        """Identify specific knowledge gaps and learning weaknesses"""
        
        # Get detailed question-level performance
        query = select(QuizAnswer).options(
            selectinload(QuizAnswer.question).selectinload(Question.topic),
            selectinload(QuizAnswer.attempt)
        ).join(QuizAttempt).where(
            and_(
                QuizAttempt.student_id == request.student_id,
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.is_submitted == True
            )
        )
        
        if request.subject:
            query = query.join(Quiz).join(Topic).where(Topic.subject == request.subject)
        
        result = await db.execute(query)
        answers = result.scalars().all()
        
        # Analyze patterns in incorrect answers
        incorrect_answers = [answer for answer in answers if not answer.is_correct]
        
        gap_analysis = {}
        for answer in incorrect_answers:
            question = answer.question
            topic = question.topic.name if question.topic else "General"
            difficulty = question.difficulty_level.value
            
            if topic not in gap_analysis:
                gap_analysis[topic] = {
                    "total_incorrect": 0,
                    "by_difficulty": {"easy": 0, "medium": 0, "hard": 0},
                    "question_types": {},
                    "common_mistakes": []
                }
            
            gap_analysis[topic]["total_incorrect"] += 1
            gap_analysis[topic]["by_difficulty"][difficulty] += 1
            
            q_type = str(question.question_type) if question.question_type else "multiple_choice"
            if q_type not in gap_analysis[topic]["question_types"]:
                gap_analysis[topic]["question_types"][q_type] = 0
            gap_analysis[topic]["question_types"][q_type] += 1
        
        prompt = f"""
Analyze these knowledge gaps and learning weaknesses:

Student ID: {request.student_id}
Subject Focus: {request.subject or 'All subjects'}
Incorrect Answer Analysis: {json.dumps(gap_analysis, indent=2)}

Identify:
1. Specific knowledge gaps by topic and concept
2. Learning pattern weaknesses
3. Skill deficiencies
4. Conceptual misunderstandings
5. Targeted remediation strategies
6. Prerequisites that may be missing

Format as JSON:
{{
  "knowledge_gaps": [
    {{
      "topic": "Linear Equations",
      "specific_gaps": ["Solving multi-step equations", "Word problem translation"],
      "severity": "high",
      "prerequisite_gaps": ["Basic algebraic manipulation"]
    }}
  ],
  "learning_patterns": [
    "Struggles with word problems across all topics",
    "Difficulty with multi-step problem solving"
  ],
  "skill_deficiencies": [
    "Mathematical reasoning",
    "Problem decomposition"
  ],
  "conceptual_misunderstandings": [
    "Confuses equation solving steps",
    "Misinterprets problem context"
  ],
  "remediation_strategies": [
    {{
      "gap": "Linear Equations",
      "strategy": "Step-by-step guided practice",
      "resources": ["Visual equation solver", "Practice worksheets"],
      "timeline": "2-3 weeks"
    }}
  ],
  "priority_order": ["Linear Equations", "Word Problems", "Basic Operations"]
}}
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.ai_service._make_request(messages)
        
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                analysis = json.loads(json_str)
                
                # Get student name
                from ...student_management.models.student import Student
                student_query = select(Student).where(Student.id == request.student_id)
                student_result = await db.execute(student_query)
                student = student_result.scalar_one_or_none()
                student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
                
                return WeaknessAnalysisResponse(
                    student_id=request.student_id,
                    student_name=student_name,
                    knowledge_gaps=analysis.get("knowledge_gaps", []),
                    learning_patterns=analysis.get("learning_patterns", []),
                    skill_deficiencies=analysis.get("skill_deficiencies", []),
                    conceptual_misunderstandings=analysis.get("conceptual_misunderstandings", []),
                    remediation_strategies=analysis.get("remediation_strategies", []),
                    priority_order=analysis.get("priority_order", [])
                )
        except Exception as e:
            logger.error(f"Weakness analysis parsing error: {e}")
        
        # Fallback analysis
        weak_topics = list(gap_analysis.keys())
        
        # Get student name
        from ...student_management.models.student import Student
        student_query = select(Student).where(Student.id == request.student_id)
        student_result = await db.execute(student_query)
        student = student_result.scalar_one_or_none()
        student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
        
        return WeaknessAnalysisResponse(
            student_id=request.student_id,
            student_name=student_name,
            knowledge_gaps=[{"topic": topic, "severity": "medium"} for topic in weak_topics[:3]],
            learning_patterns=["Requires detailed analysis"],
            skill_deficiencies=["To be determined"],
            conceptual_misunderstandings=["Needs assessment"],
            remediation_strategies=[{"gap": "General", "strategy": "Focused practice"}],
            priority_order=weak_topics[:5]
        )
    
    async def generate_exam_prep_plan(
        self,
        db: AsyncSession,
        request: ExamPrepRequest,
        tenant_id: UUID
    ) -> ExamPrepResponse:
        """Generate AI-powered exam preparation plan"""
        
        # Get student's performance in relevant subjects/topics
        query = select(QuizAttempt).options(
            selectinload(QuizAttempt.quiz),
            selectinload(QuizAttempt.answers).selectinload(QuizAnswer.question)
        ).where(
            and_(
                QuizAttempt.student_id == request.student_id,
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.is_submitted == True
            )
        )
        
        if request.exam_subjects:
            query = query.join(Quiz).join(Topic).where(Topic.subject.in_(request.exam_subjects))
        
        result = await db.execute(query)
        attempts = result.scalars().all()
        
        # Calculate days until exam
        days_until_exam = (request.exam_date - datetime.now().date()).days if request.exam_date else 30
        
        prompt = f"""
Create a comprehensive exam preparation plan:

Student ID: {request.student_id}
Exam Date: {request.exam_date}
Days Until Exam: {days_until_exam}
Exam Subjects: {request.exam_subjects or 'Not specified'}
Exam Type: {request.exam_type or 'General'}
Study Hours Available: {request.daily_study_hours or 'Not specified'} hours per day

Student Performance Data: {json.dumps([{
    "subject": attempt.quiz.topic.subject if attempt.quiz.topic else "Unknown",
    "score": attempt.percentage,
    "date": attempt.created_at.isoformat()
} for attempt in attempts[-10:]], indent=2)}

Create detailed preparation plan including:
1. Day-by-day study schedule
2. Topic prioritization based on performance
3. Practice question recommendations
4. Review sessions timing
5. Mock exam schedule
6. Last-minute revision plan
7. Stress management tips

Format as JSON:
{{
  "study_schedule": {{
    "week_1": {{
      "focus": "Foundation review",
      "daily_tasks": ["Review weak topics", "Practice problems"],
      "goals": ["Strengthen basics"]
    }}
  }},
  "topic_priorities": [
    {{
      "subject": "Mathematics",
      "topics": ["Algebra", "Geometry"],
      "priority": "high",
      "allocated_hours": 10
    }}
  ],
  "practice_plan": {{
    "daily_questions": 20,
    "mock_exams": [
      {{"date": "2024-01-15", "subjects": ["Math", "Science"], "duration": 180}}
    ],
    "review_sessions": ["Every Sunday - comprehensive review"]
  }},
  "revision_strategy": {{
    "final_week": ["Quick revision of all topics", "Solve previous papers"],
    "last_day": ["Light review", "Relaxation techniques"]
  }},
  "success_metrics": [
    "Complete 80% of practice questions",
    "Score 85%+ in mock exams"
  ]
}}
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.ai_service._make_request(messages)
        
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                plan = json.loads(json_str)
                
                # Get student name
                from ...student_management.models.student import Student
                student_query = select(Student).where(Student.id == request.student_id)
                student_result = await db.execute(student_query)
                student = student_result.scalar_one_or_none()
                student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
                
                return ExamPrepResponse(
                    student_id=request.student_id,
                    student_name=student_name,
                    exam_date=request.exam_date,
                    study_schedule=plan.get("study_schedule", {}),
                    topic_priorities=plan.get("topic_priorities", []),
                    practice_plan=plan.get("practice_plan", {}),
                    revision_strategy=plan.get("revision_strategy", {}),
                    success_metrics=plan.get("success_metrics", []),
                    estimated_readiness=85.0
                )
        except Exception as e:
            logger.error(f"Exam prep parsing error: {e}")
        
        # Fallback plan
        # Get student name
        from ...student_management.models.student import Student
        student_query = select(Student).where(Student.id == request.student_id)
        student_result = await db.execute(student_query)
        student = student_result.scalar_one_or_none()
        student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
        
        return ExamPrepResponse(
            student_id=request.student_id,
            student_name=student_name,
            exam_date=request.exam_date,
            study_schedule={"daily": {"tasks": ["Study and practice"]}},
            topic_priorities=[{"subject": "General", "priority": "medium"}],
            practice_plan={"daily_questions": 10},
            revision_strategy={"approach": "Regular review"},
            success_metrics=["Consistent daily practice"],
            estimated_readiness=70.0
        )
    
    async def predict_performance(
        self,
        db: AsyncSession,
        request: PerformancePredictionRequest,
        tenant_id: UUID
    ) -> PerformancePredictionResponse:
        """Predict student performance for upcoming assessments"""
        
        # Get historical performance data
        query = select(QuizAttempt).options(
            selectinload(QuizAttempt.quiz)
        ).where(
            and_(
                QuizAttempt.student_id == request.student_id,
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.is_submitted == True
            )
        ).order_by(QuizAttempt.created_at)
        
        result = await db.execute(query)
        attempts = result.scalars().all()
        
        if len(attempts) < 3:
            return PerformancePredictionResponse(
                student_id=request.student_id,
                predicted_score=70.0,
                confidence_level=0.3,
                performance_trend="insufficient_data",
                risk_factors=["Limited historical data"],
                improvement_potential=20.0,
                recommendations=["Take more practice quizzes to improve predictions"]
            )
        
        # Prepare performance trend data
        performance_history = []
        for i, attempt in enumerate(attempts):
            performance_history.append({
                "sequence": i + 1,
                "date": attempt.created_at.isoformat(),
                "score": attempt.percentage,
                "subject": attempt.quiz.subject,
                "quiz_type": "general"
            })
        
        prompt = f"""
Predict student performance for upcoming assessment:

Student ID: {request.student_id}
Assessment Subject: {request.assessment_subject or 'General'}
Assessment Type: {request.assessment_type or 'Quiz'}
Assessment Date: {request.assessment_date or 'Not specified'}

Historical Performance: {json.dumps(performance_history, indent=2)}

Analyze and predict:
1. Expected score range
2. Performance trend analysis
3. Confidence level in prediction
4. Risk factors that might affect performance
5. Improvement potential
6. Specific recommendations for better performance

Format as JSON:
{{
  "predicted_score": 78.5,
  "score_range": {{"min": 70, "max": 85}},
  "confidence_level": 0.8,
  "performance_trend": "improving/stable/declining",
  "trend_analysis": "Student shows consistent improvement over last 5 assessments",
  "risk_factors": [
    "Inconsistent performance in complex topics",
    "Time management issues"
  ],
  "improvement_potential": 15.0,
  "recommendations": [
    "Focus on time management practice",
    "Review weak topics identified in recent quizzes"
  ],
  "success_probability": 0.75
}}
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.ai_service._make_request(messages)
        
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                prediction = json.loads(json_str)
                
                # Get student name
                from ...student_management.models.student import Student
                student_query = select(Student).where(Student.id == request.student_id)
                student_result = await db.execute(student_query)
                student = student_result.scalar_one_or_none()
                student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
                
                return PerformancePredictionResponse(
                    student_id=request.student_id,
                    student_name=student_name,
                    predicted_score=prediction.get("predicted_score", 0.0),
                    confidence_level=prediction.get("confidence_level", 0.0),
                    performance_trend=prediction.get("performance_trend", "stable"),
                    risk_factors=prediction.get("risk_factors", []),
                    improvement_potential=prediction.get("improvement_potential", 0.0),
                    recommendations=prediction.get("recommendations", [])
                )
        except Exception as e:
            logger.error(f"Performance prediction parsing error: {e}")
        
        # Fallback prediction based on recent average
        recent_scores = [attempt.percentage for attempt in attempts[-5:]]
        avg_score = sum(recent_scores) / len(recent_scores)
        
        # Get student name
        from ...student_management.models.student import Student
        student_query = select(Student).where(Student.id == request.student_id)
        student_result = await db.execute(student_query)
        student = student_result.scalar_one_or_none()
        student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
        
        return PerformancePredictionResponse(
            student_id=request.student_id,
            student_name=student_name,
            predicted_score=avg_score,
            confidence_level=0.6,
            performance_trend="stable",
            risk_factors=["Limited analysis available"],
            improvement_potential=10.0,
            recommendations=["Continue regular practice"]
        )