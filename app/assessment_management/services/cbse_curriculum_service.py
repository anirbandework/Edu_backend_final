from typing import List, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from ...services.base_service import BaseService
from ..models.cbse_curriculum_models import (
    BookChunk, CBSESamplePaper, PaperSection, SectionQuestion
)
from .ai_integration_service import AIService
from ...core.config_assessment import assessment_settings
import logging

logger = logging.getLogger(__name__)
import json

class CBSEContentService(BaseService[BookChunk]):
    def __init__(self, db: AsyncSession):
        super().__init__(BookChunk, db)
        self.ai_service = AIService()
    
    async def generate_book_chunks(self, subject: str, chapter_content: str, tenant_id: UUID) -> List[BookChunk]:
        """AI-powered book chunk generation"""
        
        prompt = f"""
        Break down this {subject.value} chapter content into digestible chunks for Class X students.
        Create 3-5 chunks with:
        1. Chunk title
        2. Main content (200-300 words each)
        3. Key concepts (3-5 per chunk)
        4. Learning objectives
        
        Chapter content: {chapter_content[:2000]}
        
        Return as JSON array with fields: title, content, key_concepts, learning_objectives
        """
        
        try:
            messages = [{"role": "user", "content": prompt}]
            ai_response = await self.ai_service._make_request(messages)
        except Exception as e:
            logger.error(f"AI chunk generation failed: {e}")
            ai_response = ""
        
        # Handle empty AI response
        if not ai_response or ai_response.strip() == "":
            # Create fallback chunks
            chunks_data = [
                {
                    "title": f"Introduction to {subject.value.replace('_', ' ').title()}",
                    "content": chapter_content[:300] + "...",
                    "key_concepts": ["Basic concepts", "Fundamentals", "Core principles"],
                    "learning_objectives": ["Understand basics", "Apply concepts"]
                },
                {
                    "title": f"Advanced {subject.value.replace('_', ' ').title()}",
                    "content": chapter_content[300:600] + "...",
                    "key_concepts": ["Advanced topics", "Applications", "Problem solving"],
                    "learning_objectives": ["Master advanced concepts", "Solve problems"]
                }
            ]
        else:
            try:
                chunks_data = json.loads(ai_response)
            except json.JSONDecodeError:
                # Fallback if JSON parsing fails
                chunks_data = [
                    {
                        "title": f"{subject.value.replace('_', ' ').title()} Overview",
                        "content": chapter_content[:400],
                        "key_concepts": ["Overview", "Introduction"],
                        "learning_objectives": ["Basic understanding"]
                    }
                ]
        
        chunks = []
        for i, chunk_data in enumerate(chunks_data):
            chunk = BookChunk(
                tenant_id=tenant_id,
                subject=subject,
                chapter_name=f"Chapter {i+1}",
                chunk_title=chunk_data.get("title", f"Chunk {i+1}"),
                chunk_number=i+1,
                content=chunk_data.get("content", ""),
                key_concepts=chunk_data.get("key_concepts", []),
                learning_objectives=chunk_data.get("learning_objectives", []),
                difficulty_level="medium",
                estimated_time=15
            )
            self.db.add(chunk)
            chunks.append(chunk)
        
        await self.db.commit()
        return chunks
    
    async def generate_sample_paper(self, subject: str, tenant_id: UUID) -> CBSESamplePaper:
        """Generate CBSE pattern sample paper"""
        
        paper_configs = {
            "hindi_a_002": {
                "code": "002", "sections": [
                    {"type": "section_a", "name": "Reading Comprehension", "marks": 14, "questions": 7},
                    {"type": "section_b", "name": "Applied Grammar", "marks": 16, "questions": 8},
                    {"type": "section_c", "name": "Textbook (Kshitij-2, Kritika-2)", "marks": 30, "questions": 10},
                    {"type": "section_d", "name": "Creative Writing", "marks": 20, "questions": 4}
                ]
            },
            "hindi_b_085": {
                "code": "085", "sections": [
                    {"type": "section_a", "name": "Reading Comprehension", "marks": 20, "questions": 8},
                    {"type": "section_b", "name": "Applied Grammar", "marks": 20, "questions": 10},
                    {"type": "section_c", "name": "Literature/Readers", "marks": 20, "questions": 8},
                    {"type": "section_d", "name": "Writing Skills", "marks": 20, "questions": 4}
                ]
            },
            "math_standard_041": {
                "code": "041", "sections": [
                    {"type": "section_a", "name": "MCQ + Assertion-Reason", "marks": 20, "questions": 20},
                    {"type": "section_b", "name": "Very Short Answer", "marks": 10, "questions": 5},
                    {"type": "section_c", "name": "Short Answer", "marks": 18, "questions": 6},
                    {"type": "section_d", "name": "Long Answer", "marks": 20, "questions": 4},
                    {"type": "section_e", "name": "Case-based", "marks": 12, "questions": 3}
                ]
            },
            "math_basic_241": {
                "code": "241", "sections": [
                    {"type": "section_a", "name": "MCQ + Assertion-Reason", "marks": 20, "questions": 20},
                    {"type": "section_b", "name": "Very Short Answer", "marks": 10, "questions": 5},
                    {"type": "section_c", "name": "Short Answer", "marks": 18, "questions": 6},
                    {"type": "section_d", "name": "Long Answer", "marks": 20, "questions": 4},
                    {"type": "section_e", "name": "Case-based", "marks": 12, "questions": 3}
                ]
            },
            "english_184": {
                "code": "184", "sections": [
                    {"type": "section_a", "name": "Reading Comprehension", "marks": 20, "questions": 8},
                    {"type": "section_b", "name": "Grammar + Writing", "marks": 20, "questions": 8},
                    {"type": "section_c", "name": "Literature", "marks": 40, "questions": 12}
                ]
            },
            "computer_165": {
                "code": "165", "sections": [
                    {"type": "section_a", "name": "MCQ", "marks": 12, "questions": 12},
                    {"type": "section_b", "name": "Very Short Answer", "marks": 14, "questions": 7},
                    {"type": "section_c", "name": "Short Answer", "marks": 12, "questions": 4},
                    {"type": "section_d", "name": "Long Answer", "marks": 4, "questions": 1},
                    {"type": "section_e", "name": "Case-based", "marks": 8, "questions": 2}
                ]
            },
            "social_science_087": {
                "code": "087", "sections": [
                    {"type": "section_a", "name": "MCQ", "marks": 20, "questions": 20},
                    {"type": "section_b", "name": "Very Short Answer", "marks": 8, "questions": 4},
                    {"type": "section_c", "name": "Short Answer", "marks": 15, "questions": 5},
                    {"type": "section_d", "name": "Long Answer", "marks": 25, "questions": 5},
                    {"type": "section_e", "name": "Source/Case-based + Map", "marks": 12, "questions": 3}
                ]
            }
        }
        
        config = paper_configs.get(subject)
        if not config:
            raise ValueError(f"No configuration for subject {subject}")
        
        # Create sample paper
        paper = CBSESamplePaper(
            tenant_id=tenant_id,
            subject=subject,
            paper_title=f"{subject.value.replace('_', ' ').title()} Sample Paper",
            paper_code=config["code"],
            duration_hours=3,
            theory_marks=80,
            internal_marks=20,
            instructions="Read all instructions carefully before attempting the paper.",
            sections=config["sections"]
        )
        
        self.db.add(paper)
        await self.db.commit()
        await self.db.refresh(paper)
        
        # Generate sections and questions
        for section_config in config["sections"]:
            await self._generate_paper_section(paper.id, section_config, subject)
        
        return paper
    
    async def _generate_paper_section(self, paper_id: UUID, section_config: Dict, subject: str):
        """Generate questions for a paper section"""
        
        section = PaperSection(
            paper_id=paper_id,
            section_type=section_config["type"],
            section_name=section_config["name"],
            total_marks=section_config["marks"],
            question_count=section_config["questions"],
            description=f"This section contains {section_config['questions']} questions for {section_config['marks']} marks"
        )
        
        self.db.add(section)
        await self.db.commit()
        await self.db.refresh(section)
        
        # Generate AI questions for this section
        await self._generate_section_questions(section.id, section_config, subject)
    
    async def _generate_section_questions(self, section_id: UUID, section_config: Dict, subject: str):
        """AI-generated questions for section"""
        
        prompt = f"""
        Generate {section_config['questions']} questions for {subject.value} {section_config['name']} section.
        Total marks: {section_config['marks']}
        
        For each question provide:
        1. Question text
        2. Question type (MCQ/SA/LA)
        3. Marks allocation
        4. Options (if MCQ)
        5. Correct answer
        6. Marking scheme
        
        Follow CBSE 2025-26 pattern. Return as JSON array.
        """
        
        try:
            messages = [{"role": "user", "content": prompt}]
            ai_response = await self.ai_service._make_request(messages)
        except Exception as e:
            logger.error(f"AI question generation failed: {e}")
            ai_response = ""
        
        # Handle empty AI response with fallback questions
        if not ai_response or ai_response.strip() == "":
            questions_data = self._generate_fallback_questions(section_config, subject)
        else:
            try:
                questions_data = json.loads(ai_response)
            except json.JSONDecodeError:
                questions_data = self._generate_fallback_questions(section_config, subject)
        
        for i, q_data in enumerate(questions_data):
            question = SectionQuestion(
                section_id=section_id,
                question_number=f"Q{i+1}",
                question_text=q_data.get("question_text", ""),
                question_type=q_data.get("question_type", "MCQ"),
                marks=q_data.get("marks", 1),
                options=q_data.get("options"),
                correct_answer=q_data.get("correct_answer", ""),
                marking_scheme=q_data.get("marking_scheme", "")
            )
            self.db.add(question)
        
        await self.db.commit()
    
    def _generate_fallback_questions(self, section_config: Dict, subject: str) -> List[Dict]:
        """Generate fallback questions when AI fails"""
        questions = []
        for i in range(min(section_config['questions'], 3)):
            questions.append({
                "question_text": f"Sample question {i+1} for {section_config['name']}",
                "question_type": "MCQ" if "MCQ" in section_config['name'] else "SA",
                "marks": section_config['marks'] // section_config['questions'],
                "options": {"A": "Option 1", "B": "Option 2", "C": "Option 3", "D": "Option 4"} if "MCQ" in section_config['name'] else None,
                "correct_answer": "A" if "MCQ" in section_config['name'] else "Sample answer",
                "marking_scheme": "Standard marking scheme"
            })
        return questions
    
    async def get_subject_content(self, subject: str, tenant_id: UUID) -> Dict[str, Any]:
        """Get all content for a subject"""
        
        # Get book chunks
        chunks_stmt = select(BookChunk).where(
            and_(BookChunk.subject == subject, BookChunk.tenant_id == tenant_id)
        )
        chunks_result = await self.db.execute(chunks_stmt)
        chunks = chunks_result.scalars().all()
        
        # Get sample papers
        papers_stmt = select(CBSESamplePaper).where(
            and_(CBSESamplePaper.subject == subject, CBSESamplePaper.tenant_id == tenant_id)
        )
        papers_result = await self.db.execute(papers_stmt)
        papers = papers_result.scalars().all()
        
        return {
            "subject": subject.value,
            "book_chunks": [
                {
                    "id": str(chunk.id),
                    "title": chunk.chunk_title,
                    "content": chunk.content,
                    "key_concepts": chunk.key_concepts
                } for chunk in chunks
            ],
            "sample_papers": [
                {
                    "id": str(paper.id),
                    "title": paper.paper_title,
                    "code": paper.paper_code,
                    "marks": paper.theory_marks
                } for paper in papers
            ]
        }