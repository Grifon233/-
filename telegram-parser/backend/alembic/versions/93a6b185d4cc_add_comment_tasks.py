"""add_comment_tasks

Revision ID: 93a6b185d4cc
Revises: 20260602_ai_provider
Create Date: 2026-06-03 13:43:39.023223

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '93a6b185d4cc'
down_revision: Union[str, None] = '20260602_ai_provider'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Comment Tasks table
    op.create_table(
        'comment_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('DRAFT', 'RUNNING', 'PAUSED', 'COMPLETED', 'FAILED', 'STOPPED', name='commenttaskstatus'),
                  nullable=True),
        sa.Column('policy', sa.Enum('DRAFT_ONLY', 'AUTO_PUBLISH', name='commentpolicy'), nullable=True),
        sa.Column('source_ids', sa.JSON(), nullable=True),
        sa.Column('account_ids', sa.JSON(), nullable=True),
        sa.Column('comments_per_account', sa.Integer(), nullable=True),
        sa.Column('comments_per_source', sa.Integer(), nullable=True),
        sa.Column('ai_type', sa.String(length=32), nullable=True),
        sa.Column('model', sa.String(length=50), nullable=True),
        sa.Column('provider', sa.String(length=32), nullable=True),
        sa.Column('topic', sa.String(length=255), nullable=True),
        sa.Column('min_delay', sa.Integer(), nullable=True),
        sa.Column('max_delay', sa.Integer(), nullable=True),
        sa.Column('schedule_enabled', sa.Boolean(), nullable=True),
        sa.Column('schedule_start', sa.DateTime(), nullable=True),
        sa.Column('schedule_end', sa.DateTime(), nullable=True),
        sa.Column('moderation_enabled', sa.Boolean(), nullable=True),
        sa.Column('posts_checked', sa.Integer(), nullable=True),
        sa.Column('drafts_created', sa.Integer(), nullable=True),
        sa.Column('comments_posted', sa.Integer(), nullable=True),
        sa.Column('errors_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_comment_tasks_id'), 'comment_tasks', ['id'], unique=False)
    op.create_index(op.f('ix_comment_tasks_project_id'), 'comment_tasks', ['project_id'], unique=False)

    # Comment Drafts table
    op.create_table(
        'comment_drafts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('post_id', sa.Integer(), nullable=False),
        sa.Column('post_text', sa.Text(), nullable=False),
        sa.Column('draft_text', sa.Text(), nullable=False),
        sa.Column('prompt_version', sa.String(length=32), nullable=True),
        sa.Column('model_used', sa.String(length=50), nullable=True),
        sa.Column('moderation_flagged', sa.Boolean(), nullable=True),
        sa.Column('moderation_reason', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=True),
        sa.Column('approved_by', sa.String(length=255), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('published_message_id', sa.Integer(), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['comment_tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_id'], ['telegram_sources.id']),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_comment_drafts_id'), 'comment_drafts', ['id'], unique=False)

    # Comment Logs table
    op.create_table(
        'comment_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('source_id', sa.Integer(), nullable=True),
        sa.Column('draft_id', sa.Integer(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['comment_tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.ForeignKeyConstraint(['source_id'], ['telegram_sources.id']),
        sa.ForeignKeyConstraint(['draft_id'], ['comment_drafts.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_comment_logs_id'), 'comment_logs', ['id'], unique=False)


def downgrade() -> None:
    op.drop_table('comment_logs')
    op.drop_table('comment_drafts')
    op.drop_table('comment_tasks')