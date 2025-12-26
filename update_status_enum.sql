-- Update status column from enum to string
ALTER TABLE exams ADD COLUMN status_new VARCHAR(50);
UPDATE exams SET status_new = status::text;
ALTER TABLE exams DROP COLUMN status;
ALTER TABLE exams RENAME COLUMN status_new TO status;
ALTER TABLE exams ALTER COLUMN status SET NOT NULL;
ALTER TABLE exams ALTER COLUMN status SET DEFAULT 'draft';

-- Update marking_status column in student_exam_marks
ALTER TABLE student_exam_marks ADD COLUMN marking_status_new VARCHAR(50);
UPDATE student_exam_marks SET marking_status_new = marking_status::text;
ALTER TABLE student_exam_marks DROP COLUMN marking_status;
ALTER TABLE student_exam_marks RENAME COLUMN marking_status_new TO marking_status;
ALTER TABLE student_exam_marks ALTER COLUMN marking_status SET NOT NULL;
ALTER TABLE student_exam_marks ALTER COLUMN marking_status SET DEFAULT 'pending';