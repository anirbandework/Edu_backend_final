#!/usr/bin/env python3

import os
import asyncio
import requests
from app.services.ai_service import AIService
from app.schemas.quiz_schemas import QuestionType, DifficultyLevel

async def test_ai_service():
    """Test AI service directly"""
    
    print("=== AI Service Debug Test ===")
    
    # Check environment
    api_key = os.getenv("PERPLEXITY_API_KEY")
    print(f"API Key configured: {'Yes' if api_key else 'No'}")
    if api_key:
        print(f"API Key starts with: {api_key[:10]}...")
    
    # Test direct API call
    print("\n=== Testing Direct API Call ===")
    
    if api_key:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.1-sonar-large-128k-online",
            "messages": [
                {"role": "user", "content": "Generate one simple math question about addition for grade 3. Return only: Question: [question] Answer: [answer]"}
            ],
            "temperature": 0.3,
            "max_tokens": 500
        }
        
        try:
            response = requests.post(
                "https://api.perplexity.ai/chat/completions", 
                headers=headers, 
                json=payload, 
                timeout=30
            )
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                print(f"AI Generated: {content}")
            else:
                print(f"API Error: {response.text}")
                
        except Exception as e:
            print(f"Request failed: {e}")
    
    # Test AI Service
    print("\n=== Testing AI Service ===")
    
    ai_service = AIService()
    
    try:
        questions = await ai_service.generate_questions(
            topic="Addition",
            subject="Mathematics",
            grade_level=3,
            question_type=QuestionType.MULTIPLE_CHOICE,
            difficulty=DifficultyLevel.EASY,
            count=1
        )
        
        print(f"Generated {len(questions)} questions:")
        for i, q in enumerate(questions):
            print(f"Q{i+1}: {q['question_text']}")
            print(f"Answer: {q['correct_answer']}")
            
    except Exception as e:
        print(f"AI Service failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_ai_service())