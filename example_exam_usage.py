#!/usr/bin/env python3
"""
Example usage of the Exam Management System
Demonstrates flexible marking schemes for different schools
"""

import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"
TENANT_ID = "your-tenant-id"
SCHOOL_AUTHORITY_ID = "your-authority-id"

# Example 1: Physical Education Exam with Custom Marking
def create_physical_exam():
    """Create a physical education exam with custom marking scheme"""
    exam_data = {
        "exam_name": "Physical Fitness Assessment",
        "exam_code": "PE_2024_Q1",
        "exam_type": "physical",
        "description": "Comprehensive physical fitness evaluation",
        "academic_year": "2023-24",
        "term": "Quarter 1",
        "subject": "Physical Education",
        "grade_levels": [9, 10, 11, 12],
        "exam_date": (datetime.now() + timedelta(days=7)).isoformat(),
        "duration_minutes": 120,
        
        # Custom configuration for this school
        "exam_config": {
            "venue": "School Sports Ground",
            "equipment_required": ["Stopwatch", "Measuring Tape", "Weighing Scale"],
            "weather_dependent": True,
            "backup_date": (datetime.now() + timedelta(days=14)).isoformat()
        },
        
        # Flexible marking scheme
        "marking_scheme": {
            "total_marks": 100,
            "components": {
                "running_1500m": {
                    "max_marks": 25,
                    "criteria": {
                        "excellent": {"time_limit": "6:00", "marks": 25},
                        "good": {"time_limit": "7:00", "marks": 20},
                        "average": {"time_limit": "8:00", "marks": 15},
                        "below_average": {"time_limit": "9:00", "marks": 10}
                    }
                },
                "push_ups": {
                    "max_marks": 20,
                    "criteria": {
                        "boys": {"excellent": 30, "good": 25, "average": 20, "below_average": 15},
                        "girls": {"excellent": 20, "good": 15, "average": 12, "below_average": 8}
                    }
                },
                "flexibility": {
                    "max_marks": 15,
                    "measurement": "sit_and_reach_cm"
                },
                "coordination": {
                    "max_marks": 20,
                    "tests": ["ball_juggling", "ladder_drill"]
                },
                "attendance_participation": {
                    "max_marks": 20,
                    "based_on": "regular_class_participation"
                }
            }
        },
        
        "grading_criteria": {
            "A+": {"min_percentage": 90},
            "A": {"min_percentage": 80},
            "B+": {"min_percentage": 70},
            "B": {"min_percentage": 60},
            "C": {"min_percentage": 50},
            "D": {"min_percentage": 40},
            "F": {"min_percentage": 0}
        },
        
        "class_ids": ["class-id-1", "class-id-2"]
    }
    
    response = requests.post(
        f"{BASE_URL}/exam-management/exams",
        json=exam_data,
        params={"tenant_id": TENANT_ID, "created_by": SCHOOL_AUTHORITY_ID}
    )
    
    return response.json()

# Example 2: Mathematics Written Exam
def create_math_written_exam():
    """Create a mathematics written exam with different marking scheme"""
    exam_data = {
        "exam_name": "Mathematics Mid-Term Examination",
        "exam_code": "MATH_MT_2024",
        "exam_type": "written",
        "description": "Mid-term assessment covering Algebra and Geometry",
        "academic_year": "2023-24",
        "term": "Mid-Term",
        "subject": "Mathematics",
        "grade_levels": [10],
        "exam_date": (datetime.now() + timedelta(days=10)).isoformat(),
        "start_time": (datetime.now() + timedelta(days=10, hours=9)).isoformat(),
        "end_time": (datetime.now() + timedelta(days=10, hours=12)).isoformat(),
        "duration_minutes": 180,
        
        "exam_config": {
            "question_paper_code": "MATH_10_MT_2024_A",
            "calculator_allowed": False,
            "formula_sheet_provided": True,
            "answer_sheet_type": "OMR + Descriptive",
            "seating_arrangement": "alternate_seating"
        },
        
        "marking_scheme": {
            "total_marks": 100,
            "sections": {
                "section_a_mcq": {
                    "questions": 20,
                    "marks_per_question": 1,
                    "total_marks": 20,
                    "negative_marking": -0.25
                },
                "section_b_short_answer": {
                    "questions": 10,
                    "marks_per_question": 3,
                    "total_marks": 30,
                    "partial_marking": True
                },
                "section_c_long_answer": {
                    "questions": 5,
                    "marks_per_question": 10,
                    "total_marks": 50,
                    "step_marking": {
                        "method": 2,
                        "calculation": 4,
                        "final_answer": 2,
                        "diagram": 2
                    }
                }
            }
        },
        
        "grading_criteria": {
            "A1": {"min_percentage": 91, "grade_point": 10},
            "A2": {"min_percentage": 81, "grade_point": 9},
            "B1": {"min_percentage": 71, "grade_point": 8},
            "B2": {"min_percentage": 61, "grade_point": 7},
            "C1": {"min_percentage": 51, "grade_point": 6},
            "C2": {"min_percentage": 41, "grade_point": 5},
            "D": {"min_percentage": 33, "grade_point": 4},
            "E": {"min_percentage": 0, "grade_point": 0}
        },
        
        "class_ids": ["class-id-3"]
    }
    
    response = requests.post(
        f"{BASE_URL}/exam-management/exams",
        json=exam_data,
        params={"tenant_id": TENANT_ID, "created_by": SCHOOL_AUTHORITY_ID}
    )
    
    return response.json()

# Example 3: Bulk Marking for Physical Exam
def bulk_mark_physical_exam(exam_id):
    """Bulk upload marks for physical education exam"""
    bulk_marks = {
        "exam_id": exam_id,
        "batch_name": "PE_Assessment_Batch_1",
        "marks_data": [
            {
                "student_id": "student-1",
                "marks_data": {
                    "running_1500m": {
                        "time_taken": "6:30",
                        "marks_awarded": 22,
                        "performance_level": "good"
                    },
                    "push_ups": {
                        "count": 28,
                        "gender": "male",
                        "marks_awarded": 18
                    },
                    "flexibility": {
                        "sit_and_reach_cm": 25,
                        "marks_awarded": 12
                    },
                    "coordination": {
                        "ball_juggling_score": 15,
                        "ladder_drill_time": "12.5",
                        "marks_awarded": 16
                    },
                    "attendance_participation": {
                        "classes_attended": 18,
                        "total_classes": 20,
                        "marks_awarded": 18
                    }
                },
                "total_marks": 100,
                "obtained_marks": 86,
                "percentage": 86,
                "grade": "A",
                "remarks": "Excellent overall performance",
                "attendance_status": "present"
            },
            {
                "student_id": "student-2",
                "marks_data": {
                    "running_1500m": {
                        "time_taken": "7:45",
                        "marks_awarded": 18,
                        "performance_level": "average"
                    },
                    "push_ups": {
                        "count": 12,
                        "gender": "female",
                        "marks_awarded": 12
                    },
                    "flexibility": {
                        "sit_and_reach_cm": 20,
                        "marks_awarded": 10
                    },
                    "coordination": {
                        "ball_juggling_score": 8,
                        "ladder_drill_time": "15.2",
                        "marks_awarded": 12
                    },
                    "attendance_participation": {
                        "classes_attended": 16,
                        "total_classes": 20,
                        "marks_awarded": 16
                    }
                },
                "total_marks": 100,
                "obtained_marks": 68,
                "percentage": 68,
                "grade": "B+",
                "remarks": "Good effort, needs improvement in endurance",
                "attendance_status": "present"
            }
        ]
    }
    
    response = requests.post(
        f"{BASE_URL}/exam-management/exams/{exam_id}/bulk-marks",
        json=bulk_marks,
        params={"tenant_id": TENANT_ID, "marked_by": SCHOOL_AUTHORITY_ID}
    )
    
    return response.json()

# Example 4: Get Student Exam History
def get_student_history(student_id):
    """Get comprehensive exam history for a student"""
    response = requests.get(
        f"{BASE_URL}/exam-management/students/{student_id}/exam-history",
        params={"tenant_id": TENANT_ID}
    )
    
    return response.json()

# Example 5: Get Exam Analytics
def get_exam_analytics(exam_id):
    """Get detailed analytics for an exam"""
    response = requests.get(
        f"{BASE_URL}/exam-management/exams/{exam_id}/analytics",
        params={"tenant_id": TENANT_ID}
    )
    
    return response.json()

if __name__ == "__main__":
    print("=== Exam Management System Demo ===")
    
    # Create different types of exams
    print("\n1. Creating Physical Education Exam...")
    pe_exam = create_physical_exam()
    print(f"Created PE Exam: {pe_exam.get('id', 'Failed')}")
    
    print("\n2. Creating Mathematics Written Exam...")
    math_exam = create_math_written_exam()
    print(f"Created Math Exam: {math_exam.get('id', 'Failed')}")
    
    # Bulk mark the PE exam
    if pe_exam.get('id'):
        print(f"\n3. Bulk marking PE Exam...")
        bulk_result = bulk_mark_physical_exam(pe_exam['id'])
        print(f"Bulk marking result: {bulk_result}")
        
        # Get analytics
        print(f"\n4. Getting PE Exam Analytics...")
        analytics = get_exam_analytics(pe_exam['id'])
        print(f"Analytics: {analytics}")
    
    print("\n=== Demo Complete ===")