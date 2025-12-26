"""merge_page_permissions_with_quiz

Revision ID: 8163f616453f
Revises: add_page_permissions, create_quiz_classes_simple
Create Date: 2025-12-26 20:52:58.860497

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8163f616453f'
down_revision: Union[str, None] = ('add_page_permissions', 'create_quiz_classes_simple')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
