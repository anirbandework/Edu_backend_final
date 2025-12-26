"""create quiz classes table simple

Revision ID: create_quiz_classes_simple
Revises: add_quiz_multiple_classes
Create Date: 2024-01-20 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'create_quiz_classes_simple'
down_revision = 'add_quiz_multiple_classes'
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

def downgrade():
    op.drop_table('quiz_classes')