"""concept name_key and mastery elo default 1000

Revision ID: 217bb547e324
Revises: 6d0dbf5b54f3
Create Date: 2026-11-12 18:00:00.000000

concepts.name_key: the normalized name (lowercase, punctuation -> space, whitespace
collapsed; same as jobs.questions.concept_key). Unique, so "Glycolysis." and
"glycolysis" can only ever be one concept.

mastery.elo: ratings start at 1000 (#25), matching the fixed question rating.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '217bb547e324'
down_revision: Union[str, Sequence[str], None] = '6d0dbf5b54f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('concepts', sa.Column('name_key', sa.Text(), nullable=True))
    # backfill any existing rows with the same normalization concept_key() uses
    op.execute(r"""
        UPDATE concepts
        SET name_key = trim(regexp_replace(regexp_replace(lower(name), '[^\w\s]', ' ', 'g'), '\s+', ' ', 'g'))
    """)
    op.alter_column('concepts', 'name_key', nullable=False)
    op.create_unique_constraint('concepts_name_key_key', 'concepts', ['name_key'])

    op.alter_column('mastery', 'elo', server_default=sa.text('1000'))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('mastery', 'elo', server_default=sa.text('1200'))
    op.drop_constraint('concepts_name_key_key', 'concepts', type_='unique')
    op.drop_column('concepts', 'name_key')
