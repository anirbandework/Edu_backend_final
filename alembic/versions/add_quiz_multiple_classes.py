"""add quiz multiple classes support

Revision ID: add_quiz_multiple_classes
Revises: 34935f04b6c7
Create Date: 2024-01-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'add_quiz_multiple_classes'
down_revision = '34935f04b6c7'
branch_labels = None
depends_on = None

def upgrade():
    # Create quiz_classes association table
    op.create_table('quiz_classes',
        sa.Column('quiz_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('class_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ),
        sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.id'], ),
        sa.PrimaryKeyConstraint('quiz_id', 'class_id')
    )
    
    # Migrate existing data from quizzes.class_id to quiz_classes table
    op.execute("""
        INSERT INTO quiz_classes (quiz_id, class_id)
        SELECT id, class_id FROM quizzes WHERE class_id IS NOT NULL
    """)
    
    # Remove class_id column from quizzes table (if exists)
    try:
        op.drop_constraint('quizzes_class_id_fkey', 'quizzes', type_='foreignkey')
    except:
        pass
    try:
        op.drop_index('ix_quizzes_class_id', table_name='quizzes')
    except:
        pass
    try:
        op.drop_column('quizzes', 'class_id')
    except:
        pass

def downgrade():
    # Add class_id column back to quizzes table
    op.add_column('quizzes', sa.Column('class_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index('ix_quizzes_class_id', 'quizzes', ['class_id'], unique=False)
    op.create_foreign_key('quizzes_class_id_fkey', 'quizzes', 'classes', ['class_id'], ['id'])
    
    # Migrate data back (only first class if multiple)
    op.execute("""
        UPDATE quizzes SET class_id = (
            SELECT class_id FROM quiz_classes WHERE quiz_classes.quiz_id = quizzes.id LIMIT 1
        )
    """)
    
    # Drop quiz_classes table
    op.drop_table('quiz_classes')