"""add_performance_indexes

Revision ID: 13e5663ce64f
Revises: a4548c7c2326
Create Date: 2026-06-19 22:19:38.489543

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector


# revision identifiers, used by Alembic.
revision: str = '13e5663ce64f'
down_revision: Union[str, None] = 'a4548c7c2326'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('idx_jobs_source', 'job_postings', ['source'], unique=False, schema='jobs')
    op.create_index('idx_jobs_posting_date', 'job_postings', [sa.text('posting_date DESC')], unique=False, schema='jobs')
    op.create_index('idx_applications_user_status', 'applications', ['user_id', 'status'], unique=False, schema='applications')


def downgrade() -> None:
    op.drop_index('idx_applications_user_status', table_name='applications', schema='applications')
    op.drop_index('idx_jobs_posting_date', table_name='job_postings', schema='jobs')
    op.drop_index('idx_jobs_source', table_name='job_postings', schema='jobs')
