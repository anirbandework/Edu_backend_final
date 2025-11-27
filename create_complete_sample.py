#!/usr/bin/env python3

import asyncio
from uuid import uuid4
from app.core.database import get_db
from sqlalchemy import text

async def create_complete_sample():
    """Create complete sample data including tenant, topic, and questions"""
    
    async for db in get_db():
        try:
            # Sample IDs
            tenant_id = "550e8400-e29b-41d4-a716-446655440000"
            topic_id = "550e8400-e29b-41d4-a716-446655440001"
            
            # Check if tenant exists
            tenant_check = await db.execute(
                text("SELECT id FROM tenants WHERE id = :tenant_id"),
                {"tenant_id": tenant_id}
            )
            
            if not tenant_check.fetchone():
                print("Creating sample tenant...")
                await db.execute(
                    text("""
                        INSERT INTO tenants (id, name, domain, subscription_type, is_active, created_at, updated_at, is_deleted)
                        VALUES (:id, :name, :domain, :subscription_type, true, NOW(), NOW(), false)
                    """),
                    {
                        "id": tenant_id,
                        "name": "Sample School",
                        "domain": "sample-school",
                        "subscription_type": "premium"
                    }
                )
            
            # Check if topic exists
            topic_check = await db.execute(
                text("SELECT id FROM topics WHERE id = :topic_id"),
                {"topic_id": topic_id}
            )
            
            if not topic_check.fetchone():
                print("Creating sample topic...")
                await db.execute(
                    text("""
                        INSERT INTO topics (id, tenant_id, name, description, subject, grade_level, created_at, updated_at, is_deleted)
                        VALUES (:id, :tenant_id, :name, :description, :subject, :grade_level, NOW(), NOW(), false)
                    """),
                    {
                        "id": topic_id,
                        "tenant_id": tenant_id,
                        "name": "Linear Equations",
                        "description": "Solving linear equations in one variable",
                        "subject": "Mathematics",
                        "grade_level": 10
                    }
                )
            
            # Check if questions exist
            question_check = await db.execute(
                text("SELECT COUNT(*) FROM questions WHERE topic_id = :topic_id"),
                {"topic_id": topic_id}
            )
            question_count = question_check.fetchone()[0]
            
            if question_count == 0:
                print("Creating sample questions...")
                
                questions = [
                    {
                        "id": str(uuid4()),
                        "question_text": "Solve for x: 2x + 5 = 15",
                        "question_type": "multiple_choice",
                        "difficulty_level": "easy",
                        "options": '{"A": "x = 5", "B": "x = 10", "C": "x = 7.5", "D": "x = 2.5"}',
                        "correct_answer": "A",
                        "explanation": "2x + 5 = 15. Subtract 5: 2x = 10. Divide by 2: x = 5",
                        "points": 1
                    },
                    {
                        "id": str(uuid4()),
                        "question_text": "Solve: 3x - 7 = 2x + 8",
                        "question_type": "multiple_choice",
                        "difficulty_level": "easy",
                        "options": '{"A": "x = 15", "B": "x = 1", "C": "x = -1", "D": "x = 8"}',
                        "correct_answer": "A",
                        "explanation": "3x - 7 = 2x + 8. Subtract 2x: x - 7 = 8. Add 7: x = 15",
                        "points": 1
                    },
                    {
                        "id": str(uuid4()),
                        "question_text": "Solve: 4(x - 3) = 2(x + 1)",
                        "question_type": "multiple_choice",
                        "difficulty_level": "medium",
                        "options": '{"A": "x = 7", "B": "x = 5", "C": "x = 3", "D": "x = 1"}',
                        "correct_answer": "A",
                        "explanation": "4(x - 3) = 2(x + 1) → 4x - 12 = 2x + 2 → 2x = 14 → x = 7",
                        "points": 2
                    },
                    {
                        "id": str(uuid4()),
                        "question_text": "Find x: (2x + 1)/3 = (x - 2)/2",
                        "question_type": "multiple_choice",
                        "difficulty_level": "medium",
                        "options": '{"A": "x = -7", "B": "x = 7", "C": "x = -5", "D": "x = 5"}',
                        "correct_answer": "A",
                        "explanation": "Cross multiply: 2(2x + 1) = 3(x - 2) → 4x + 2 = 3x - 6 → x = -8",
                        "points": 2
                    },
                    {
                        "id": str(uuid4()),
                        "question_text": "Solve: x² - 5x + 6 = 0",
                        "question_type": "multiple_choice",
                        "difficulty_level": "medium",
                        "options": '{"A": "x = 2, 3", "B": "x = 1, 6", "C": "x = -2, -3", "D": "x = 5, 6"}',
                        "correct_answer": "A",
                        "explanation": "Factor: (x-2)(x-3) = 0, so x = 2 or x = 3",
                        "points": 2
                    },
                    {
                        "id": str(uuid4()),
                        "question_text": "Solve: |2x - 3| = 7",
                        "question_type": "short_answer",
                        "difficulty_level": "hard",
                        "options": None,
                        "correct_answer": "x = 5 or x = -2",
                        "explanation": "2x - 3 = 7 or 2x - 3 = -7. So x = 5 or x = -2",
                        "points": 3
                    }
                ]
                
                for q in questions:
                    await db.execute(
                        text("""
                            INSERT INTO questions (
                                id, tenant_id, topic_id, question_text, question_type, 
                                difficulty_level, options, correct_answer, explanation, 
                                points, version, original_source, created_at, updated_at, is_deleted
                            ) VALUES (
                                :id, :tenant_id, :topic_id, :question_text, :question_type,
                                :difficulty_level, :options, :correct_answer, :explanation,
                                :points, 1, 'sample_data', NOW(), NOW(), false
                            )
                        """),
                        {
                            "id": q["id"],
                            "tenant_id": tenant_id,
                            "topic_id": topic_id,
                            "question_text": q["question_text"],
                            "question_type": q["question_type"],
                            "difficulty_level": q["difficulty_level"],
                            "options": q["options"],
                            "correct_answer": q["correct_answer"],
                            "explanation": q["explanation"],
                            "points": q["points"]
                        }
                    )
                
                print(f"Created {len(questions)} sample questions")
            else:
                print(f"Found {question_count} existing questions")
            
            await db.commit()
            print("Complete sample data creation finished!")
            
        except Exception as e:
            print(f"Error: {e}")
            await db.rollback()
        finally:
            break

if __name__ == "__main__":
    asyncio.run(create_complete_sample())