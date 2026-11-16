"""quiz status and skip reason

Revision ID: b3185048a82e
Revises: 217bb547e324
Create Date: 2026-11-16 12:00:00.000000

quizzes.status: how question generation ended. 'ready' (questions saved), 'empty' (nothing
worth asking) or 'failed' (an error). NULL while generating. Before this, all three looked
the same in the DB: a quiz with 0 questions.

quizzes.skip_reason: why an 'empty' quiz has no questions. 'not_educational' and
'too_little_content' come from the model; 'ungrounded' (the grounding check dropped every
question) and 'no_transcript' come from our code.

Existing quizzes stay NULL in both; their outcome was only ever in the server log.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3185048a82e'
down_revision: Union[str, Sequence[str], None] = '217bb547e324'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('quizzes', sa.Column('status', sa.Text(), nullable=True))
    op.create_check_constraint('quizzes_status_check', 'quizzes', "status IN ('ready', 'empty', 'failed')")
    op.add_column('quizzes', sa.Column('skip_reason', sa.Text(), nullable=True))
    op.create_check_constraint(
        'quizzes_skip_reason_check', 'quizzes',
        "skip_reason IN ('not_educational', 'too_little_content', 'ungrounded', 'no_transcript')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('quizzes_skip_reason_check', 'quizzes', type_='check')
    op.drop_column('quizzes', 'skip_reason')
    op.drop_constraint('quizzes_status_check', 'quizzes', type_='check')
    op.drop_column('quizzes', 'status')
