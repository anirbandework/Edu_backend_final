-- Update exam_type column from enum to string
-- First, add a new temporary column
ALTER TABLE exams ADD COLUMN exam_type_new VARCHAR(50);

-- Copy data from enum to string
UPDATE exams SET exam_type_new = exam_type::text;

-- Drop the old enum column
ALTER TABLE exams DROP COLUMN exam_type;

-- Rename the new column
ALTER TABLE exams RENAME COLUMN exam_type_new TO exam_type;

-- Add NOT NULL constraint
ALTER TABLE exams ALTER COLUMN exam_type SET NOT NULL;

-- Add index
CREATE INDEX idx_exam_type ON exams(exam_type);

-- Update exam_templates table similarly
ALTER TABLE exam_templates ADD COLUMN template_type_new VARCHAR(50);
UPDATE exam_templates SET template_type_new = template_type::text;
ALTER TABLE exam_templates DROP COLUMN template_type;
ALTER TABLE exam_templates RENAME COLUMN template_type_new TO template_type;
ALTER TABLE exam_templates ALTER COLUMN template_type SET NOT NULL;

-- Drop the enum type if no longer needed
-- DROP TYPE IF EXISTS examtype;