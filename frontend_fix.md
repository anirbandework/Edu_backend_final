# Frontend Fix for 422 Error

## Issues in Your Request:

1. **Missing `options` for true_false question**
2. **Missing `points` for each question**

## Your Current Request (Broken):
```json
{
  "class_ids": ["8aa55744-23cb-4d18-86df-7841d9a20d88", "1f8187a4-d08c-4c76-81fe-856e6e2edc12", "71a12956-ac40-400d-94b3-c318beb40f58"],
  "title": "fff",
  "description": "fff", 
  "instructions": "",
  "subject": "maths",
  "time_limit": 1800,
  "questions": [
    {
      "question_text": "fff",
      "question_type": "true_false",
      "difficulty_level": "easy",
      "correct_answer": "True"
      // MISSING: options and points
    }
  ],
  "allow_retakes": false,
  "show_results_immediately": true

}
```

## Fixed Request:
```json
{
  "class_ids": ["8aa55744-23cb-4d18-86df-7841d9a20d88", "1f8187a4-d08c-4c76-81fe-856e6e2edc12", "71a12956-ac40-400d-94b3-c318beb40f58"],
  "title": "fff",
  "description": "fff", 
  "instructions": "",
  "subject": "maths",

  "time_limit": 1800,
  "questions": [
    {
      "question_text": "fff",
      "question_type": "true_false",
      "difficulty_level": "easy",
      "options": {
        "True": "Yes",
        "False": "No"
      },
      "correct_answer": "True",
      "points": 1
    }
  ],
  "allow_retakes": false,
  "show_results_immediately": true
}
```

## Frontend Code Fix:

```javascript
// Add these fields to your form data before sending:

// 1. For true_false questions, always add options:
if (question.question_type === 'true_false') {
  question.options = {
    "True": "Yes", 
    "False": "No"
  };
}

// 2. Ensure every question has points:
question.points = parseInt(question.points) || 1;
```

## Required Fields Checklist:
- ✅ title
- ✅ subject  
- ✅ grade_level (optional)
- ✅ questions array
- For each question:
  - ✅ question_text
  - ✅ question_type
  - ✅ difficulty_level
  - ✅ correct_answer
  - ❌ **points** (ADD THIS)
  - ❌ **options** (ADD FOR TRUE_FALSE)