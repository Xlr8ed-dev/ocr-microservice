"""add requested content to ocr jobs

Revision ID: f1a2b3c4d5e6
Revises: 805873735a30
Create Date: 2026-11-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '805873735a30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'document_ocr_jobs',
        sa.Column('requested_keys', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'document_ocr_jobs',
        sa.Column('requested_prompt', sa.Text(), nullable=True),
    )
    op.add_column(
        'image_ocr_jobs',
        sa.Column('requested_keys', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'image_ocr_jobs',
        sa.Column('requested_prompt', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('image_ocr_jobs', 'requested_prompt')
    op.drop_column('image_ocr_jobs', 'requested_keys')
    op.drop_column('document_ocr_jobs', 'requested_prompt')
    op.drop_column('document_ocr_jobs', 'requested_keys')
