# app/services/ai_report_service.py

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
import json
from datetime import datetime, timedelta, date

from ..models.quiz_question_models import Quiz, QuizAttempt, QuizAnswer, Question, Topic
from ..schemas.ai_analytics_schemas import (
    ReportGenerationRequest, ReportGenerationResponse,
    InterventionRequest, InterventionResponse
)
from .ai_integration_service import AIService

import logging
logger = logging.getLogger(__name__)

class AIReportService:
    def __init__(self):
        self.ai_service = AIService()
    
    async def generate_student_progress_report(
        self,
        db: AsyncSession,
        request: ReportGenerationRequest,
        tenant_id: UUID
    ) -> ReportGenerationResponse:
        """Generate comprehensive student progress report"""
        
        if not request.student_id:
            raise ValueError("Student ID required for student progress report")
        
        # Get student's performance data (avoiding answers to prevent enum issues)
        query = select(QuizAttempt).options(
            selectinload(QuizAttempt.quiz).selectinload(Quiz.topic)
        ).where(
            and_(
                QuizAttempt.student_id == request.student_id,
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.is_submitted == True
            )
        ).order_by(desc(QuizAttempt.created_at))
        
        # Apply time period filter if specified
        if request.time_period:
            days_back = self._get_days_from_period(request.time_period)
            cutoff_date = datetime.now() - timedelta(days=days_back)
            query = query.where(QuizAttempt.created_at >= cutoff_date)
        
        result = await db.execute(query)
        attempts = result.scalars().all()
        
        if not attempts:
            return ReportGenerationResponse(
                report_id=str(uuid4()),
                report_type="student_progress",
                generated_content={"message": "No data available for the specified period"},
                summary="No assessment data found",
                recommendations=["Encourage student to participate in more assessments"]
            )
        
        # Prepare comprehensive data for AI analysis
        student_data = {
            "student_id": str(request.student_id),
            "total_assessments": len(attempts),
            "time_period": request.time_period or "all_time",
            "performance_summary": {
                "average_score": sum(a.percentage for a in attempts) / len(attempts),
                "highest_score": max(a.percentage for a in attempts),
                "lowest_score": min(a.percentage for a in attempts),
                "total_points_earned": sum(a.total_score for a in attempts),
                "total_points_possible": sum(a.max_score for a in attempts)
            },
            "subject_breakdown": self._analyze_subject_performance(attempts),
            "recent_trends": self._analyze_performance_trends(attempts),
            "assessment_details": [
                {
                    "date": attempt.created_at.isoformat(),
                    "quiz_title": attempt.quiz.title,
                    "subject": attempt.quiz.topic.subject if attempt.quiz.topic else "Unknown",
                    "score": attempt.percentage,
                    "time_taken": None  # Would need to calculate from timestamps
                }
                for attempt in attempts[:10]  # Last 10 assessments
            ]
        }
        
        prompt = f"""
Generate a comprehensive student progress report based on this data:

{json.dumps(student_data, indent=2)}

Create a detailed report including:
1. Executive Summary of student performance
2. Academic Strengths and Achievements
3. Areas for Improvement
4. Subject-wise Performance Analysis
5. Learning Progress Trends
6. Specific Recommendations for Student
7. Recommendations for Teachers/Parents
8. Goal Setting for Next Period

Format as JSON:
{{
  "executive_summary": "Comprehensive overview of student's academic performance...",
  "academic_strengths": [
    "Excellent performance in algebraic concepts",
    "Consistent improvement in problem-solving skills"
  ],
  "improvement_areas": [
    "Geometry concepts need reinforcement",
    "Time management in complex problems"
  ],
  "subject_analysis": {{
    "Mathematics": {{
      "performance": "Above Average",
      "trend": "Improving",
      "key_insights": "Strong in algebra, needs work in geometry"
    }}
  }},
  "learning_trends": [
    "Steady improvement over the assessment period",
    "Better performance in recent assessments"
  ],
  "student_recommendations": [
    "Focus on geometry practice with visual aids",
    "Continue strong performance in algebra"
  ],
  "teacher_parent_recommendations": [
    "Provide additional geometry resources",
    "Encourage continued practice in strong areas"
  ],
  "goals_next_period": [
    "Achieve 85%+ average in all subjects",
    "Improve geometry scores by 15 points"
  ],
  "charts_data": {{
    "performance_over_time": [75, 78, 82, 85],
    "subject_comparison": {{"Math": 82, "Science": 78}}
  }}
}}
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.ai_service._make_request(messages)
        
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                report_data = json.loads(json_str)
                
                # Get student name
                from ...staff_management.models.member import Member  # student-subject id is a members.id now
                student_query = select(Member).where(Member.id == request.student_id)
                student_result = await db.execute(student_query)
                student = student_result.scalar_one_or_none()
                student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
                
                return ReportGenerationResponse(
                    report_id=str(uuid4()),
                    report_type="student_progress",
                    generated_content=report_data,
                    summary=report_data.get("executive_summary", ""),
                    recommendations=report_data.get("student_recommendations", []),
                    charts_data=report_data.get("charts_data"),
                    report_title=f"Progress Report - {student_name}",
                    student_name=student_name,
                    generated_for=f"{student_name} - Academic Progress Report"
                )
        except Exception as e:
            logger.error(f"Report generation parsing error: {e}")
        
        # Get student name for fallback
        from ...staff_management.models.member import Member  # student-subject id is a members.id now
        student_query = select(Member).where(Member.id == request.student_id)
        student_result = await db.execute(student_query)
        student = student_result.scalar_one_or_none()
        student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
        
        # Fallback report
        avg_score = sum(a.percentage for a in attempts) / len(attempts)
        return ReportGenerationResponse(
            report_id=str(uuid4()),
            report_type="student_progress",
            generated_content={
                "summary": f"Student completed {len(attempts)} assessments with average score of {avg_score:.1f}%",
                "performance": "Basic analysis completed"
            },
            summary=f"Average performance: {avg_score:.1f}%",
            recommendations=["Continue regular assessment participation"],
            report_title=f"Progress Report - {student_name}",
            student_name=student_name,
            generated_for=f"{student_name} - Academic Progress Report"
        )
    
    async def generate_class_summary_report(
        self,
        db: AsyncSession,
        request: ReportGenerationRequest,
        tenant_id: UUID
    ) -> ReportGenerationResponse:
        """Generate class performance summary report"""
        
        if not request.class_id:
            raise ValueError("Class ID required for class summary report")
        
        # Get all students' performance in the class
        # Note: This would require a proper class-student relationship in your models
        # For now, we'll use a placeholder approach
        
        query = select(QuizAttempt).options(
            selectinload(QuizAttempt.quiz).selectinload(Quiz.topic)
        ).where(
            and_(
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.is_submitted == True
            )
        )
        
        # Apply time period filter
        if request.time_period:
            days_back = self._get_days_from_period(request.time_period)
            cutoff_date = datetime.now() - timedelta(days=days_back)
            query = query.where(QuizAttempt.created_at >= cutoff_date)
        
        result = await db.execute(query)
        attempts = result.scalars().all()
        
        # Group by student for class analysis
        student_performance = {}
        for attempt in attempts:
            student_id = str(attempt.student_id)
            if student_id not in student_performance:
                student_performance[student_id] = []
            student_performance[student_id].append({
                "score": attempt.percentage,
                "subject": attempt.quiz.topic.subject if attempt.quiz.topic else "Unknown",
                "date": attempt.created_at.isoformat()
            })
        
        class_data = {
            "class_id": str(request.class_id),
            "total_students": len(student_performance),
            "total_assessments": len(attempts),
            "time_period": request.time_period or "all_time",
            "class_statistics": {
                "average_score": sum(a.percentage for a in attempts) / len(attempts) if attempts else 0,
                "highest_score": max(a.percentage for a in attempts) if attempts else 0,
                "lowest_score": min(a.percentage for a in attempts) if attempts else 0,
                "pass_rate": len([a for a in attempts if a.percentage >= 60]) / len(attempts) * 100 if attempts else 0
            },
            "subject_performance": self._analyze_subject_performance(attempts),
            "student_distribution": self._analyze_student_distribution(student_performance)
        }
        
        prompt = f"""
Generate a comprehensive class performance summary report:

{json.dumps(class_data, indent=2)}

Create detailed analysis including:
1. Class Performance Overview
2. Subject-wise Analysis
3. Student Performance Distribution
4. Top Performers and At-Risk Students
5. Common Strengths and Weaknesses
6. Teaching Effectiveness Insights
7. Recommendations for Curriculum Adjustments
8. Individual Student Attention Needs

Format as JSON:
{{
  "class_overview": "Overall class performance summary...",
  "performance_highlights": [
    "85% of students showing improvement",
    "Strong performance in Mathematics"
  ],
  "areas_of_concern": [
    "15% of students below passing threshold",
    "Declining performance in specific topics"
  ],
  "subject_insights": {{
    "Mathematics": {{
      "class_average": 78.5,
      "performance_trend": "improving",
      "common_mistakes": ["Geometry calculations", "Word problems"]
    }}
  }},
  "student_categories": {{
    "high_performers": 8,
    "average_performers": 15,
    "at_risk_students": 3
  }},
  "teaching_recommendations": [
    "Increase focus on geometry concepts",
    "Implement peer tutoring for struggling students"
  ],
  "curriculum_suggestions": [
    "Add more visual aids for geometry",
    "Increase practice time for word problems"
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
                report_data = json.loads(json_str)
                
                # Get class name
                from ...class_management.models.class_model import Class
                class_query = select(Class).where(Class.id == request.class_id)
                class_result = await db.execute(class_query)
                class_obj = class_result.scalar_one_or_none()
                class_name = class_obj.name if class_obj else "Unknown Class"
                
                return ReportGenerationResponse(
                    report_id=str(uuid4()),
                    report_type="class_summary",
                    generated_content=report_data,
                    summary=report_data.get("class_overview", ""),
                    recommendations=report_data.get("teaching_recommendations", []),
                    report_title=f"Class Summary - {class_name}",
                    class_name=class_name,
                    generated_for=f"{class_name} - Performance Summary"
                )
        except Exception as e:
            logger.error(f"Class report parsing error: {e}")
        
        # Fallback report
        # Get class name
        from ...class_management.models.class_model import Class
        class_query = select(Class).where(Class.id == request.class_id)
        class_result = await db.execute(class_query)
        class_obj = class_result.scalar_one_or_none()
        class_name = class_obj.name if class_obj else "Unknown Class"
        
        return ReportGenerationResponse(
            report_id=str(uuid4()),
            report_type="class_summary",
            generated_content={"summary": "Class analysis completed"},
            summary="Basic class performance analysis",
            recommendations=["Continue monitoring student progress"],
            report_title=f"Class Summary - {class_name}",
            class_name=class_name,
            generated_for=f"{class_name} - Performance Summary"
        )
    
    async def generate_parent_report(
        self,
        db: AsyncSession,
        request: ReportGenerationRequest,
        tenant_id: UUID
    ) -> ReportGenerationResponse:
        """Generate parent-friendly progress report"""
        
        if not request.student_id:
            raise ValueError("Student ID required for parent report")
        
        # Get student performance data (similar to student report but parent-focused)
        query = select(QuizAttempt).options(
            selectinload(QuizAttempt.quiz)
        ).where(
            and_(
                QuizAttempt.student_id == request.student_id,
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.is_submitted == True
            )
        ).order_by(desc(QuizAttempt.created_at))
        
        if request.time_period:
            days_back = self._get_days_from_period(request.time_period)
            cutoff_date = datetime.now() - timedelta(days=days_back)
            query = query.where(QuizAttempt.created_at >= cutoff_date)
        
        result = await db.execute(query)
        attempts = result.scalars().all()
        
        prompt = f"""
Generate a parent-friendly progress report for their child:

Student Performance Summary:
- Total Assessments: {len(attempts)}
- Average Score: {sum(a.percentage for a in attempts) / len(attempts) if attempts else 0:.1f}%
- Recent Performance: {"Improving" if len(attempts) >= 2 and attempts[0].percentage > attempts[-1].percentage else "Stable"}

Create a warm, encouraging report including:
1. Celebration of Achievements
2. Areas of Growth and Progress
3. Gentle Areas for Support
4. How Parents Can Help at Home
5. Positive Reinforcement Suggestions
6. Next Steps and Goals

Use encouraging, non-technical language appropriate for parents.

Format as JSON:
{{
  "achievements_celebration": [
    "Your child has shown excellent improvement in mathematics",
    "Consistent participation in all assessments"
  ],
  "growth_areas": [
    "Making steady progress in problem-solving skills",
    "Developing stronger analytical thinking"
  ],
  "support_areas": [
    "Could benefit from additional practice in geometry",
    "Time management skills during assessments"
  ],
  "parent_support_tips": [
    "Practice math problems together for 15 minutes daily",
    "Use visual aids and real-world examples for geometry"
  ],
  "encouragement_strategies": [
    "Praise effort and improvement, not just scores",
    "Celebrate small wins and progress milestones"
  ],
  "next_steps": [
    "Continue current study routine",
    "Focus on geometry concepts next month"
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
                report_data = json.loads(json_str)
                
                # Get student name
                from ...staff_management.models.member import Member  # student-subject id is a members.id now
                student_query = select(Member).where(Member.id == request.student_id)
                student_result = await db.execute(student_query)
                student = student_result.scalar_one_or_none()
                student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
                
                return ReportGenerationResponse(
                    report_id=str(uuid4()),
                    report_type="parent_report",
                    generated_content=report_data,
                    summary="Your child is making good progress in their studies",
                    recommendations=report_data.get("parent_support_tips", []),
                    report_title=f"Parent Report - {student_name}",
                    student_name=student_name,
                    generated_for=f"Parent Report for {student_name}"
                )
        except Exception as e:
            logger.error(f"Parent report parsing error: {e}")
        
        # Get student name for fallback
        from ...staff_management.models.member import Member  # student-subject id is a members.id now
        student_query = select(Member).where(Member.id == request.student_id)
        student_result = await db.execute(student_query)
        student = student_result.scalar_one_or_none()
        student_name = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
        
        return ReportGenerationResponse(
            report_id=str(uuid4()),
            report_type="parent_report",
            generated_content={"message": "Your child is participating well in assessments"},
            summary="Positive progress noted",
            recommendations=["Continue supporting your child's learning journey"],
            report_title=f"Parent Report - {student_name}",
            student_name=student_name,
            generated_for=f"Parent Report for {student_name}"
        )
    
    async def identify_intervention_needs(
        self,
        db: AsyncSession,
        request: InterventionRequest,
        tenant_id: UUID
    ) -> InterventionResponse:
        """Identify students needing intervention and suggest strategies"""
        
        at_risk_students = []
        all_student_data = []
        
        # Get student names first
        from ...staff_management.models.member import Member  # student-subject id is a members.id now
        student_names = {}
        for student_id in request.student_ids:
            student_query = select(Member).where(Member.id == student_id)
            student_result = await db.execute(student_query)
            student = student_result.scalar_one_or_none()
            if student:
                student_names[str(student_id)] = f"{student.first_name} {student.last_name}"
            else:
                student_names[str(student_id)] = "Unknown Student"
        
        for student_id in request.student_ids:
            # Get recent performance for each student
            query = select(QuizAttempt).where(
                and_(
                    QuizAttempt.student_id == student_id,
                    QuizAttempt.tenant_id == tenant_id,
                    QuizAttempt.is_submitted == True
                )
            ).order_by(desc(QuizAttempt.created_at)).limit(10)
            
            result = await db.execute(query)
            attempts = result.scalars().all()
            
            if attempts:
                avg_score = sum(a.percentage for a in attempts) / len(attempts)
                recent_trend = "declining" if len(attempts) >= 3 and attempts[0].percentage < attempts[2].percentage else "stable"
                
                student_data = {
                    "student_id": str(student_id),
                    "student_name": student_names[str(student_id)],
                    "average_score": avg_score,
                    "recent_performance": [a.percentage for a in attempts[:5]],
                    "trend": recent_trend,
                    "total_assessments": len(attempts)
                }
                
                all_student_data.append(student_data)
                
                # Check if student meets at-risk criteria
                if avg_score < (request.risk_threshold * 100):
                    at_risk_students.append(student_data)
        
        if not at_risk_students:
            return InterventionResponse(
                at_risk_students=[],
                intervention_strategies=[],
                priority_actions=["Continue monitoring student progress"],
                monitoring_plan={"frequency": "weekly", "metrics": ["quiz_scores"]},
                success_indicators=["Maintain current performance levels"]
            )
        
        prompt = f"""
Analyze at-risk students and recommend intervention strategies:

At-Risk Students: {json.dumps(at_risk_students, indent=2)}
Risk Threshold: {request.risk_threshold * 100}%
Intervention Type: {request.intervention_type}

Provide comprehensive intervention plan including:
1. Individual student risk assessment
2. Targeted intervention strategies
3. Priority actions for immediate implementation
4. Monitoring and progress tracking plan
5. Success indicators and milestones
6. Resource requirements

Format as JSON:
{{
  "student_assessments": [
    {{
      "student_id": "uuid",
      "risk_level": "high/medium/low",
      "primary_concerns": ["Low quiz scores", "Declining trend"],
      "recommended_interventions": ["One-on-one tutoring", "Modified assignments"]
    }}
  ],
  "intervention_strategies": [
    {{
      "strategy": "Individualized Learning Plan",
      "target_students": ["uuid1", "uuid2"],
      "implementation": "Weekly one-on-one sessions",
      "timeline": "4-6 weeks",
      "resources_needed": ["Tutor", "Additional materials"]
    }}
  ],
  "priority_actions": [
    "Schedule immediate parent conferences",
    "Implement daily check-ins"
  ],
  "monitoring_plan": {{
    "frequency": "weekly",
    "metrics": ["quiz_scores", "assignment_completion", "engagement"],
    "review_schedule": "Bi-weekly progress meetings"
  }},
  "success_indicators": [
    "15% improvement in quiz scores within 4 weeks",
    "Increased assignment completion rate"
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
                intervention_data = json.loads(json_str)
                
                return InterventionResponse(
                    at_risk_students=intervention_data.get("student_assessments", []),
                    intervention_strategies=intervention_data.get("intervention_strategies", []),
                    priority_actions=intervention_data.get("priority_actions", []),
                    monitoring_plan=intervention_data.get("monitoring_plan", {}),
                    success_indicators=intervention_data.get("success_indicators", [])
                )
        except Exception as e:
            logger.error(f"Intervention analysis parsing error: {e}")
        
        # Fallback intervention plan
        return InterventionResponse(
            at_risk_students=[{"student_id": str(s["student_id"]), "student_name": s.get("student_name", "Unknown"), "risk_level": "medium"} for s in at_risk_students],
            intervention_strategies=[{"strategy": "Additional support", "implementation": "Regular check-ins"}],
            priority_actions=["Schedule teacher meetings", "Provide additional resources"],
            monitoring_plan={"frequency": "weekly", "metrics": ["performance_tracking"]},
            success_indicators=["Improved assessment scores", "Better engagement"]
        )
    
    def _get_days_from_period(self, period: str) -> int:
        """Convert time period string to days"""
        period_map = {
            "last_week": 7,
            "last_month": 30,
            "last_quarter": 90,
            "last_semester": 180,
            "last_year": 365
        }
        return period_map.get(period, 30)
    
    def _analyze_subject_performance(self, attempts: List) -> Dict[str, Any]:
        """Analyze performance by subject"""
        subject_data = {}
        for attempt in attempts:
            subject = attempt.quiz.topic.subject if attempt.quiz.topic else "Unknown"
            if subject not in subject_data:
                subject_data[subject] = {"scores": [], "count": 0}
            subject_data[subject]["scores"].append(attempt.percentage)
            subject_data[subject]["count"] += 1
        
        for subject, data in subject_data.items():
            data["average"] = sum(data["scores"]) / len(data["scores"])
            data["trend"] = "stable"  # Would need more complex analysis for trends
        
        return subject_data
    
    def _analyze_topic_performance(self, attempts: List) -> Dict[str, Any]:
        """Analyze performance by topic"""
        topic_data = {}
        for attempt in attempts:
            for answer in attempt.answers:
                if answer.question.topic:
                    topic_name = answer.question.topic.name
                    if topic_name not in topic_data:
                        topic_data[topic_name] = {"correct": 0, "total": 0}
                    topic_data[topic_name]["total"] += 1
                    if answer.is_correct:
                        topic_data[topic_name]["correct"] += 1
        
        for topic, data in topic_data.items():
            data["accuracy"] = (data["correct"] / data["total"]) * 100 if data["total"] > 0 else 0
        
        return topic_data
    
    def _analyze_difficulty_performance(self, attempts: List) -> Dict[str, Any]:
        """Analyze performance by difficulty level"""
        difficulty_data = {"easy": {"correct": 0, "total": 0}, "medium": {"correct": 0, "total": 0}, "hard": {"correct": 0, "total": 0}}
        
        for attempt in attempts:
            for answer in attempt.answers:
                difficulty = str(answer.question.difficulty_level) if answer.question.difficulty_level else "medium"
                if difficulty in difficulty_data:
                    difficulty_data[difficulty]["total"] += 1
                    if answer.is_correct:
                        difficulty_data[difficulty]["correct"] += 1
        
        for difficulty, data in difficulty_data.items():
            data["accuracy"] = (data["correct"] / data["total"]) * 100 if data["total"] > 0 else 0
        
        return difficulty_data
    
    def _analyze_performance_trends(self, attempts: List) -> List[str]:
        """Analyze performance trends over time"""
        if len(attempts) < 3:
            return ["Insufficient data for trend analysis"]
        
        recent_scores = [a.percentage for a in attempts[:5]]
        older_scores = [a.percentage for a in attempts[-5:]]
        
        recent_avg = sum(recent_scores) / len(recent_scores)
        older_avg = sum(older_scores) / len(older_scores)
        
        trends = []
        if recent_avg > older_avg + 5:
            trends.append("Showing improvement over time")
        elif recent_avg < older_avg - 5:
            trends.append("Performance declining, needs attention")
        else:
            trends.append("Consistent performance maintained")
        
        return trends
    
    def _analyze_student_distribution(self, student_performance: Dict) -> Dict[str, Any]:
        """Analyze distribution of student performance"""
        if not student_performance:
            return {}
        
        student_averages = []
        for student_id, performances in student_performance.items():
            if performances:
                avg = sum(p["score"] for p in performances) / len(performances)
                student_averages.append(avg)
        
        if not student_averages:
            return {}
        
        return {
            "high_performers": len([s for s in student_averages if s >= 85]),
            "average_performers": len([s for s in student_averages if 60 <= s < 85]),
            "at_risk_students": len([s for s in student_averages if s < 60]),
            "class_average": sum(student_averages) / len(student_averages)
        }