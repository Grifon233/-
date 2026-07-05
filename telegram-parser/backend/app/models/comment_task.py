from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Text, Boolean, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
import enum
from datetime import datetime
from app.db.base_class import Base


class CommentTaskStatus(str, enum.Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class CommentPolicy(str, enum.Enum):
    DRAFT_ONLY = "draft_only"  # Only create drafts, no auto-publish
    AUTO_PUBLISH = "auto_publish"  # Publish without manual approval (only for own sources)


class CommentTargetMode(str, enum.Enum):
    CHANNEL_POSTS = "channel_posts"
    GROUP_CONTEXT = "group_context"


class CommentSourceStateStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    JOIN_REQUESTED = "join_requested"
    FAILED = "failed"
    SKIPPED = "skipped"


class CommentTask(Base):
    """NeuroCommenting task - AI-powered comment generation for channel posts."""
    __tablename__ = "comment_tasks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, default=1, index=True)

    # Task settings
    status = Column(Enum(CommentTaskStatus, values_callable=lambda x: [e.value for e in x]), default=CommentTaskStatus.DRAFT)
    policy = Column(Enum(CommentPolicy, values_callable=lambda x: [e.value for e in x]), default=CommentPolicy.DRAFT_ONLY)

    # Source selection - IDs of TelegramSource records
    source_ids = Column(JSON, nullable=False, default=list)
    target_mode = Column(
        Enum(CommentTargetMode, values_callable=lambda x: [e.value for e in x]),
        default=CommentTargetMode.CHANNEL_POSTS,
        nullable=False,
    )
    target_modes = Column(JSON, nullable=False, default=lambda: [CommentTargetMode.CHANNEL_POSTS.value])

    # Account selection - IDs of Account records
    account_ids = Column(JSON, nullable=False, default=list)

    # Limits per account
    comments_per_account = Column(Integer, default=10)
    comments_per_source = Column(Integer, default=3)

    # AI settings
    ai_type = Column(String(32), default="commenting")  # referencing AIType
    model = Column(String(50), default="gpt-4o-mini")
    provider = Column(String(32), default="openai")
    topic = Column(String(255), nullable=True)  # comment topic/theme

    # Timing
    min_delay = Column(Integer, default=60)  # seconds between comments
    max_delay = Column(Integer, default=180)  # seconds between comments
    schedule_enabled = Column(Boolean, default=False)
    schedule_start = Column(DateTime, nullable=True)  # when to start
    schedule_end = Column(DateTime, nullable=True)  # when to stop

    # Moderation
    moderation_enabled = Column(Boolean, default=True)

    # Statistics
    posts_checked = Column(Integer, default=0)
    drafts_created = Column(Integer, default=0)
    comments_posted = Column(Integer, default=0)
    errors_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project")
    drafts = relationship("CommentDraft", back_populates="task", cascade="all, delete-orphan")
    logs = relationship("CommentLog", back_populates="task", cascade="all, delete-orphan")
    source_states = relationship("CommentTaskSourceState", back_populates="task", cascade="all, delete-orphan")


class CommentTaskSourceState(Base):
    """Per-task progress marker for one Telegram source.

    This is the queue memory for neuro-commenting: once a source is
    marked DONE, the same task will not return to it until the operator
    explicitly creates/resets a task. New accounts added to a task pick
    from the remaining PENDING/FAILED sources, not from already finished
    ones.
    """
    __tablename__ = "comment_task_source_states"
    __table_args__ = (
        UniqueConstraint("task_id", "source_id", name="uq_comment_task_source_state"),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("comment_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("telegram_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(
        Enum(CommentSourceStateStatus, values_callable=lambda x: [e.value for e in x]),
        default=CommentSourceStateStatus.PENDING,
        nullable=False,
        index=True,
    )
    attempts = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, nullable=True)
    last_processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    task = relationship("CommentTask", back_populates="source_states")
    source = relationship("TelegramSource")
    account = relationship("Account")


class CommentDraft(Base):
    """AI-generated comment draft awaiting approval or auto-publish."""
    __tablename__ = "comment_drafts"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("comment_tasks.id", ondelete="CASCADE"), nullable=False, index=True)

    # Source context
    source_id = Column(Integer, ForeignKey("telegram_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    post_id = Column(Integer, nullable=False)  # Telegram message ID
    post_text = Column(Text, nullable=False)

    # AI generation
    draft_text = Column(Text, nullable=False)
    prompt_version = Column(String(32), nullable=True)
    model_used = Column(String(50), nullable=True)

    # Moderation
    moderation_flagged = Column(Boolean, default=False)
    moderation_reason = Column(Text, nullable=True)

    # Approval workflow
    status = Column(String(32), default="pending")  # pending, approved, rejected, published, skipped
    approved_by = Column(String(255), nullable=True)  # "auto" or username
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Publication result
    published_message_id = Column(Integer, nullable=True)
    published_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    task = relationship("CommentTask", back_populates="drafts")
    source = relationship("TelegramSource")
    account = relationship("Account")


class CommentLog(Base):
    """Audit log for comment actions."""
    __tablename__ = "comment_logs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("comment_tasks.id", ondelete="CASCADE"), nullable=False, index=True)

    # What happened
    action = Column(String(64), nullable=False)  # created_draft, approved, rejected, published, skipped, error
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    source_id = Column(Integer, ForeignKey("telegram_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    draft_id = Column(Integer, ForeignKey("comment_drafts.id", ondelete="SET NULL"), nullable=True, index=True)

    # Details
    details = Column(JSON, nullable=True)  # additional context
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    task = relationship("CommentTask", back_populates="logs")
    account = relationship("Account")
    source = relationship("TelegramSource")
    draft = relationship("CommentDraft")
