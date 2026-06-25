# app/services/assessment/ai_service.py

import os
import json
import requests
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
from ..schemas.quiz_validation_schemas import QuestionType, DifficultyLevel

import logging
logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        # Load environment variables more robustly
        load_dotenv(override=True)
        self.api_key = os.getenv("PERPLEXITY_API_KEY")
        
        # Debug logging
        if not self.api_key:
            logger.warning("PERPLEXITY_API_KEY not found in environment")
            # Try loading from different possible locations
            import pathlib
            current_dir = pathlib.Path(__file__).parent.parent.parent
            env_file = current_dir / ".env"
            if env_file.exists():
                load_dotenv(env_file, override=True)
                self.api_key = os.getenv("PERPLEXITY_API_KEY")
                logger.info(f"Loaded .env from: {env_file}")
        
        logger.info(f"AI Service initialized - API Key: {'Found' if self.api_key else 'Missing'}")
        self.base_url = "https://api.perplexity.ai/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def _make_request(self, messages: List[Dict], model: str = "sonar") -> str:
        """Make request to Perplexity API"""
        if not self.api_key:
            logger.error("PERPLEXITY_API_KEY not configured")
            # Try to reload environment one more time
            load_dotenv(override=True)
            self.api_key = os.getenv("PERPLEXITY_API_KEY")
            if not self.api_key:
                return "Error: PERPLEXITY_API_KEY not configured"
            
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,  # Lower for more consistent educational content
            "max_tokens": 4000
        }
        
        try:
            logger.info(f"Making API request to Perplexity with model: {model}")
            response = requests.post(self.base_url, headers=self.headers, json=payload, timeout=45)
            logger.info(f"API Response Status: {response.status_code}")
            
            if response.status_code != 200:
                logger.info(f"API Error Response: {response.text}")
                return f"Error: API returned {response.status_code} - {response.text}"
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            logger.info(f"API Success - Content length: {len(content)}")
            return content
            
        except requests.exceptions.Timeout:
            logger.error("Request timeout")
            return "Error: Request timeout"
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed - {str(e)}")
            return f"Error: API request failed - {str(e)}"
        except (KeyError, IndexError) as e:
            logger.error(f"Invalid API response format - {str(e)}")
            return f"Error: Invalid API response format - {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error - {str(e)}")
            return f"Error: {str(e)}"
    
    async def generate_questions(
        self, 
        topic: str, 
        subject: str, 
        grade_level: int,
        question_type: QuestionType,
        difficulty: DifficultyLevel,
        count: int = 5,
        learning_objectives: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Generate questions using AI"""
        
        # Enhanced prompt for NCERT-based questions
        prompt = f"""
You are an expert Indian educator familiar with NCERT curriculum and CBSE board patterns. Generate {count} high-quality {difficulty.value} level {question_type.value} questions for Class {grade_level} students.

Subject: {subject}
Topic: {topic}
{f'Learning Objectives: {learning_objectives}' if learning_objectives else ''}

Requirements:
- Follow NCERT curriculum and CBSE board question patterns
- Questions should be similar to those found in NCERT textbooks and sample papers
- Use Indian educational context and examples
- Ensure correct answers are accurate and well-explained
- For Mathematics: Include step-by-step solutions
- For Science: Include scientific reasoning and real-world applications
- For Social Science: Include Indian historical/geographical context
- Points: Easy=1-2, Medium=2-3, Hard=3-5

IMPORTANT: Return ONLY a valid JSON array with NO additional text:
[
  {{
    "question_text": "Clear, specific question based on NCERT curriculum",
    "options": {{"A": "option1", "B": "option2", "C": "option3", "D": "option4"}} or null,
    "correct_answer": "A" or "exact answer",
    "explanation": "Detailed step-by-step explanation with NCERT reference",
    "points": 2
  }}
]
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self._make_request(messages)
        
        logger.debug(f"AI Response received: {response[:200]}...")  # Debug log
        
        # Check if response contains error
        if response.startswith("Error:"):
            logger.info(f"AI API Error: {response}")
            return self._generate_fallback_questions(count, question_type, difficulty, topic)
        
        try:
            # Extract JSON from response
            start = response.find('[')
            end = response.rfind(']') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                logger.debug(f"Extracted JSON: {json_str[:200]}...")  # Debug log
                questions = json.loads(json_str)
                
                # Validate questions
                valid_questions = []
                for q in questions:
                    if self._validate_question(q):
                        valid_questions.append(q)
                
                if valid_questions:
                    logger.info(f"Successfully generated {len(valid_questions)} valid questions")
                    return valid_questions[:count]
                else:
                    logger.info("No valid questions found in AI response")
                    
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {e}")
        except Exception as e:
            logger.error(f"AI parsing error: {e}")
        
        # Fallback to sample questions if AI fails
        logger.info("Falling back to sample questions")
        return self._generate_fallback_questions(count, question_type, difficulty, topic)
    
    def _validate_question(self, question: Dict) -> bool:
        """Validate if a question has required fields"""
        required_fields = ["question_text", "correct_answer", "explanation", "points"]
        return all(field in question and question[field] for field in required_fields)
    
    def _generate_fallback_questions(self, count: int, question_type: QuestionType, difficulty: DifficultyLevel, topic: str) -> List[Dict[str, Any]]:
        """Generate NCERT-style fallback questions when AI fails"""
        questions = []
        points = 1 if difficulty == DifficultyLevel.EASY else 2 if difficulty == DifficultyLevel.MEDIUM else 3
        
        # Better fallback questions based on common NCERT patterns
        fallback_templates = {
            "Linear Equations": {
                "multiple_choice": [
                    {
                        "question_text": "Solve for x: 2x + 5 = 15",
                        "options": {"A": "x = 5", "B": "x = 10", "C": "x = 7.5", "D": "x = 2.5"},
                        "correct_answer": "A",
                        "explanation": "2x + 5 = 15. Subtract 5 from both sides: 2x = 10. Divide by 2: x = 5"
                    },
                    {
                        "question_text": "Which of the following is a linear equation in one variable?",
                        "options": {"A": "x² + 2x = 5", "B": "3x + 7 = 0", "C": "xy + 5 = 0", "D": "x³ - 1 = 0"},
                        "correct_answer": "B",
                        "explanation": "A linear equation in one variable has degree 1. Only 3x + 7 = 0 satisfies this condition."
                    }
                ],
                "short_answer": [
                    {
                        "question_text": "Solve: 3(x - 2) = 2(x + 1)",
                        "correct_answer": "x = 8",
                        "explanation": "3(x - 2) = 2(x + 1) → 3x - 6 = 2x + 2 → 3x - 2x = 2 + 6 → x = 8"
                    }
                ]
            },
            "Quadratic Equations": {
                "multiple_choice": [
                    {
                        "question_text": "The roots of the equation x² - 5x + 6 = 0 are:",
                        "options": {"A": "2, 3", "B": "1, 6", "C": "-2, -3", "D": "5, 6"},
                        "correct_answer": "A",
                        "explanation": "x² - 5x + 6 = 0. Factoring: (x - 2)(x - 3) = 0. So x = 2 or x = 3."
                    },
                    {
                        "question_text": "The discriminant of ax² + bx + c = 0 is:",
                        "options": {"A": "b² + 4ac", "B": "b² - 4ac", "C": "4ac - b²", "D": "b² - 2ac"},
                        "correct_answer": "B",
                        "explanation": "The discriminant of a quadratic equation ax² + bx + c = 0 is Δ = b² - 4ac."
                    }
                ],
                "short_answer": [
                    {
                        "question_text": "Find the nature of roots of 2x² + 3x + 5 = 0",
                        "correct_answer": "No real roots (imaginary roots)",
                        "explanation": "Discriminant = b² - 4ac = 9 - 40 = -31 < 0. Since discriminant is negative, the equation has no real roots."
                    }
                ]
            },
            "Mathematics": {
                "multiple_choice": [
                    {
                        "question_text": "What is the value of sin 30°?",
                        "options": {"A": "1/2", "B": "√3/2", "C": "1", "D": "√2/2"},
                        "correct_answer": "A",
                        "explanation": "sin 30° = 1/2. This is a standard trigonometric value from NCERT Class 10."
                    }
                ]
            },
            "Photosynthesis": {
                "multiple_choice": [
                    {
                        "question_text": "Which gas is released during photosynthesis?",
                        "options": {"A": "Carbon dioxide", "B": "Oxygen", "C": "Nitrogen", "D": "Hydrogen"},
                        "correct_answer": "B",
                        "explanation": "During photosynthesis, plants use CO₂ and water to produce glucose and release oxygen as a byproduct."
                    }
                ],
                "short_answer": [
                    {
                        "question_text": "Write the chemical equation for photosynthesis.",
                        "correct_answer": "6CO₂ + 6H₂O + light energy → C₆H₁₂O₆ + 6O₂",
                        "explanation": "Photosynthesis converts carbon dioxide and water into glucose using light energy, releasing oxygen."
                    }
                ]
            }
        }
        
        # Use templates if available, otherwise generic questions
        if topic in fallback_templates and question_type.value in fallback_templates[topic]:
            templates = fallback_templates[topic][question_type.value]
            for i in range(min(count, len(templates))):
                question = templates[i].copy()
                question["points"] = points
                if "options" not in question:
                    question["options"] = None
                questions.append(question)
        
        # Fill remaining with generic questions if needed
        while len(questions) < count:
            i = len(questions)
            if question_type == QuestionType.MULTIPLE_CHOICE:
                questions.append({
                    "question_text": f"NCERT-style question {i+1} about {topic} (AI service unavailable)",
                    "options": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                    "correct_answer": "A",
                    "explanation": "This is a fallback question. Please check AI service configuration.",
                    "points": points
                })
            else:
                questions.append({
                    "question_text": f"NCERT-style {question_type.value} question {i+1} about {topic} (AI service unavailable)",
                    "options": None,
                    "correct_answer": "Sample answer",
                    "explanation": "This is a fallback question. Please check AI service configuration.",
                    "points": points
                })
        
        return questions
    
    async def suggest_quiz_assembly(
        self,
        available_questions: List[Dict],
        target_duration: Optional[int],
        difficulty_distribution: Optional[Dict[str, int]] = None
    ) -> Dict[str, Any]:
        """Suggest optimal question combination for quiz"""
        
        prompt = f"""
Analyze these available questions and suggest optimal quiz assembly:

Available Questions: {json.dumps(available_questions, indent=2)}
Target Duration: {target_duration} minutes
Difficulty Distribution: {difficulty_distribution or 'balanced'}

Provide recommendations for:
1. Question selection (by ID)
2. Optimal order
3. Time allocation
4. Difficulty balance
5. Total points

Format as JSON:
{{
  "selected_questions": ["question_id1", "question_id2"],
  "suggested_order": ["question_id1", "question_id2"],
  "time_per_question": {{"question_id1": 3, "question_id2": 5}},
  "difficulty_balance": {{"easy": 2, "medium": 2, "hard": 1}},
  "total_points": 10,
  "estimated_duration": 25,
  "recommendations": "..."
}}
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self._make_request(messages)
        
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                return json.loads(json_str)
        except:
            pass
        
        return {}
    
    async def grade_subjective_answer(
        self,
        question: str,
        correct_answer: str,
        student_answer: str,
        max_points: int,
        rubric: Optional[str] = None
    ) -> Dict[str, Any]:
        """Grade subjective answers using AI"""
        
        prompt = f"""
Grade this student's answer:

Question: {question}
Model Answer: {correct_answer}
Student Answer: {student_answer}
Max Points: {max_points}
{f'Rubric: {rubric}' if rubric else ''}

Provide:
1. Points earned (0 to {max_points})
2. Detailed feedback
3. Areas for improvement
4. Strengths identified

Format as JSON:
{{
  "points_earned": 3,
  "percentage": 75,
  "feedback": "...",
  "strengths": ["..."],
  "improvements": ["..."],
  "is_correct": true/false
}}
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self._make_request(messages)
        
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                return json.loads(json_str)
        except:
            pass
        
        return {"points_earned": 0, "feedback": "Unable to grade automatically"}
    
    async def analyze_class_performance(
        self,
        quiz_results: List[Dict],
        class_info: Dict
    ) -> Dict[str, Any]:
        """Analyze class performance and provide insights"""
        
        prompt = f"""
Analyze this class performance data:

Class Info: {json.dumps(class_info, indent=2)}
Quiz Results: {json.dumps(quiz_results, indent=2)}

Provide insights on:
1. Overall performance trends
2. Common mistakes/weak areas
3. Top performers
4. Students needing help
5. Teaching recommendations
6. Question difficulty analysis

Format as JSON:
{{
  "overall_stats": {{
    "average_score": 75.5,
    "pass_rate": 85,
    "difficulty_rating": "medium"
  }},
  "weak_areas": ["topic1", "topic2"],
  "strong_areas": ["topic3"],
  "at_risk_students": ["student_id1"],
  "top_performers": ["student_id2"],
  "recommendations": [
    "Review topic1 with more examples",
    "Consider additional practice for struggling students"
  ],
  "question_analysis": {{
    "easiest": "question_id1",
    "hardest": "question_id2",
    "most_missed": "question_id3"
  }}
}}
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self._make_request(messages)
        
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                return json.loads(json_str)
        except:
            pass
        
        return {}

# Legacy function for backward compatibility
async def get_gemini_reply(user_message: str) -> str:
    ai_service = AIService()
    messages = [{"role": "user", "content": user_message}]
    return await ai_service._make_request(messages)