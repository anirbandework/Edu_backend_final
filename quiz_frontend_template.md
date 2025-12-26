# Quiz Creation Frontend Template

## Development Prompt

**Task**: Create a quiz creation form with two modes:

1. **Quick Quiz Mode** - Create quiz with inline questions (new feature)
2. **Advanced Mode** - Traditional flow (select topics → questions → create)

**Requirements**:
- Build a dynamic form that allows teachers to create quizzes directly with inline questions
- Support three question types: Multiple Choice, True/False, Short Answer
- Each quiz can have mixed question formats (all three types in one quiz)
- Implement dynamic question builder with add/remove functionality
- Include proper validation for each question type
- Handle class selection (multi-select)
- Convert time limit from minutes to seconds for API
- Show/hide options field based on question type selection

**User Flow**:
1. Teacher selects "Quick Quiz" mode
2. Fills quiz details (title, subject, grade, etc.)
3. Adds questions dynamically using + button
4. For each question: selects type, fills content, sets points
5. Submits to create quiz with auto-generated topic

**Technical Notes**:
- Use the new API endpoint for inline question creation
- Validate that correct_answer matches option keys for MCQ/T-F
- Handle conditional rendering of options field
- Implement proper error handling and success feedback

## API Endpoint
```
POST /assessment/quiz/quizzes/create-with-questions?teacher_id={teacher_id}&tenant_id={tenant_id}
```

## Request Body Template

```json
{
  "class_ids": ["PUT_CLASS_ID_HERE"],
  "title": "Quiz Title Here",
  "description": "Quiz description here",
  "instructions": "Instructions for students",
  "subject": "Mathematics",
  "grade_level": 10,
  "time_limit": 900,
  "questions": [
    {
      "question_text": "What is 2 + 2?",
      "question_type": "multiple_choice",
      "difficulty_level": "easy",
      "options": {
        "A": "3",
        "B": "4",
        "C": "5",
        "D": "6"
      },
      "correct_answer": "B",
      "explanation": "Basic addition",
      "points": 1
    },
    {
      "question_text": "Is 10 greater than 5?",
      "question_type": "true_false",
      "difficulty_level": "easy",
      "options": {
        "True": "Yes",
        "False": "No"
      },
      "correct_answer": "True",
      "points": 1
    },
    {
      "question_text": "Explain the Pythagorean theorem",
      "question_type": "short_answer",
      "difficulty_level": "medium",
      "correct_answer": "a² + b² = c²",
      "explanation": "The square of the hypotenuse equals the sum of squares of the other two sides",
      "points": 3
    }
  ],
  "allow_retakes": true,
  "show_results_immediately": true
}
```

## Form Fields Required

### Quiz Details
- `title` (string, required, max 200 chars)
- `description` (string, optional)
- `instructions` (string, optional)
- `subject` (string, required, max 50 chars)
- `grade_level` (number, required, 1-12)
- `time_limit` (number, optional, seconds)
- `class_ids` (array of UUIDs, optional)
- `allow_retakes` (boolean, default false)
- `show_results_immediately` (boolean, default true)

### Question Fields (Dynamic Array)
- `question_text` (string, required)
- `question_type` (select: "multiple_choice", "true_false", "short_answer")
- `difficulty_level` (select: "easy", "medium", "hard")
- `correct_answer` (string, required)
- `explanation` (string, optional)
- `points` (number, required, min 1)
- `options` (object, conditional):
  - For multiple_choice: {"A": "text", "B": "text", "C": "text", "D": "text"}
  - For true_false: {"True": "Yes", "False": "No"}
  - For short_answer: not required

## Frontend Implementation Notes

1. **Question Type Handler**: When user selects question type, show/hide options field
2. **Dynamic Questions**: Allow adding/removing questions with + and - buttons
3. **Validation**: Ensure correct_answer matches one of the option keys for MCQ/T-F
4. **Class Selection**: Multi-select dropdown for classes
5. **Time Limit**: Optional field in minutes (convert to seconds for API)

## JavaScript Example

```javascript
const createQuiz = async (formData) => {
  const response = await fetch(`/assessment/quiz/quizzes/create-with-questions?teacher_id=${teacherId}&tenant_id=${tenantId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(formData)
  });
  
  if (response.ok) {
    const quiz = await response.json();
    console.log('Quiz created:', quiz.id);
  }
};
```

## Question Type Templates

### Multiple Choice Template
```json
{
  "question_text": "",
  "question_type": "multiple_choice",
  "difficulty_level": "easy",
  "options": {
    "A": "",
    "B": "",
    "C": "",
    "D": ""
  },
  "correct_answer": "A",
  "points": 1
}
```

### True/False Template
```json
{
  "question_text": "",
  "question_type": "true_false",
  "difficulty_level": "easy",
  "options": {
    "True": "Yes",
    "False": "No"
  },
  "correct_answer": "True",
  "points": 1
}
```

### Short Answer Template
```json
{
  "question_text": "",
  "question_type": "short_answer",
  "difficulty_level": "medium",
  "correct_answer": "",
  "points": 1
}
```