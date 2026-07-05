"""Model for runs of the three integrated external parsers.

Each parser keeps its own upstream code untouched (see
``app/services/external_parsers/``). This table records a *run*: which
parser, on which combine account, with what config, and where the
captured results live. It mirrors :class:`app.models.parsing.ParsingTask`
so the UI and endpoints follow the existing pattern.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class ExternalParserType(str, enum.Enum):
    """Which upstream parser a run belongs to."""

    # github.com/volom/telegram-channels-monitor — Telethon, realtime poll.
    MONITOR = "monitor"
    # github.com/minaton-ru/telegram-keywords-parser — Pyrogram, one-shot
    # history scan over the last N days.
    KEYWORDS = "keywords"
    # github.com/crazypeace/keyword_alert_bot — Telethon, realtime
    # event-driven alert bot with its own subscription store.
    ALERT_BOT = "alert_bot"


class ExternalParserStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"      # realtime parser stopped by the operator
    COMPLETED = "completed"  # one-shot parser finished
    FAILED = "failed"


class ExternalParserRun(Base):
    __tablename__ = "external_parser_runs"

    id = Column(Integer, primary_key=True, index=True)
    # ``native_enum=False`` keeps these as plain VARCHAR (matching the
    # ``String(32)`` columns the migration creates) and stops SQLAlchemy
    # from emitting ``::externalparsertype`` casts that reference a native
    # Postgres enum type we never create. Same workaround the project uses
    # for ``accounts.gender``. Without it, every query 500s on Postgres
    # ("тип externalparsertype не существует") while passing on SQLite.
    parser = Column(
        Enum(ExternalParserType, values_callable=lambda x: [e.value for e in x],
             native_enum=False, length=32),
        nullable=False,
    )
    status = Column(
        Enum(ExternalParserStatus, values_callable=lambda x: [e.value for e in x],
             native_enum=False, length=32),
        default=ExternalParserStatus.PENDING,
        nullable=False,
    )

    # Whose Telegram session/proxy this run uses. The bridge converts
    # the account's Pyrogram session to Telethon for MONITOR/ALERT_BOT.
    account_id = Column(
        Integer,
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        default=1,
        index=True,
    )

    # Free-form per-parser config: channels[], keywords[], bot_token,
    # time_pause, days, limit, only_with_link, etc.
    config = Column(JSON, nullable=True)

    result_count = Column(Integer, default=0)
    # CSV of captured matches (date, channel, link, keyword, sender, text).
    file_path = Column(String, nullable=True)
    # Working directory holding the generated config + run.log.
    workdir = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    account = relationship("Account")
