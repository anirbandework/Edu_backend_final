from fastapi import APIRouter
from . import (
    quiz_management_routes as quiz,
    ai_quiz_generation_routes as ai_quiz,
    ai_quiz_management_routes as ai_quiz_mgmt,
    ai_student_analytics_routes as ai_learning,
    cbse_curriculum_routes as cbse_content,
    cbse_quiz_platform_routes as cbse_quiz,
    cbse_simple_query_routes as cbse_simple,
    cbse_pdf_upload_routes as cbse_pdf,
    assignment_grading_routes as grading,
    ai_chat_integration_routes as chai_ai
)

assessment_router = APIRouter(prefix="/assessment", tags=["Assessment System"])

# Include all assessment sub-routers
assessment_router.include_router(quiz.router)
assessment_router.include_router(ai_quiz.router)
assessment_router.include_router(ai_quiz_mgmt.router)
assessment_router.include_router(ai_learning.router)
assessment_router.include_router(cbse_content.router)
assessment_router.include_router(cbse_quiz.router)
assessment_router.include_router(cbse_simple.router)
assessment_router.include_router(cbse_pdf.router)
assessment_router.include_router(grading.router)
assessment_router.include_router(chai_ai.router)

@assessment_router.get("/health")
async def assessment_health():
    """Health check for assessment system"""
    return {
        "status": "healthy",
        "system": "Assessment Management",
        "features": [
            "Quiz Management",
            "AI Question Generation",
            "AI Learning Analytics",
            "CBSE Content Management",
            "Grading System",
            "Performance Analytics"
        ]
    }