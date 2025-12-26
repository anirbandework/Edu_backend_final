"""merge exam management with existing

Revision ID: e0473961605e
Revises: assessment_models_001, create_quiz_classes_simple
Create Date: 2025-12-01 02:33:33.667021

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0473961605e'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
