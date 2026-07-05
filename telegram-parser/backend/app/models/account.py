from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Enum, ForeignKey, JSON, Float, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
import enum
from datetime import datetime
from app.db.base_class import Base
from app.db.encrypted_type import EncryptedString

class AccountStatus(str, enum.Enum):
    NEW = "new"
    WARMING = "warming"
    PRODUCTION = "production"
    BANNED = "banned"
    RESTRICTED = "restricted"

class AccountSex(str, enum.Enum):
    """Detected gender of the account owner.

    Telegram does not expose ``users.full`` gender directly in the
    public MTProto schema, so the value is best-effort:
    * ``male`` / ``female`` — when the operator manually confirms
      via the profile editor
    * ``unknown`` — default for new accounts; filled in by a future
      detection job (e.g. via the user's first/last name on a
      third-party service) — see ``TODO.md``.
    """
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"

class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    api_id = Column(Integer, nullable=False)
    api_hash = Column(EncryptedString, nullable=False)
    session_string = Column(EncryptedString, nullable=True)
    status = Column(Enum(AccountStatus, values_callable=lambda x: [e.value for e in x]), default=AccountStatus.NEW)
    proxy_id = Column(Integer, ForeignKey("proxies.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, default=1, index=True)
    note = Column(String(255), nullable=True)

    # ── Profile fields (cached from Telegram) ───────────────────────────
    # These are populated by ``POST /accounts/{id}/profile/refresh`` and
    # updated on every successful ``POST /accounts/{id}/profile``
    # write. The first/last name live on the Telegram account; bio and
    # username are read-only from the server's point of view, set
    # through ``client.update_profile`` / ``client.set_username``.
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    bio = Column(String, nullable=True)
    username = Column(String, nullable=True, index=True)
    # Path to a cached avatar on disk under ``var/avatars/``; the
    # avatar itself is fetched with ``client.get_profile_photos``.
    avatar_path = Column(String, nullable=True)
    # Raw dump of the last ``users.getFullUser`` call. We keep it
    # around so the UI can show fields we haven't surfaced yet.
    profile_cache = Column(JSON, nullable=True)
    # Cached gender (filled by the operator or by a future detector).
    # Column name is ``gender`` to match the existing frontend
    # (which was written before we added the column); the ORM
    # attribute is named ``sex`` for clarity.
    # The column is stored as VARCHAR(16) (no Postgres ENUM type was
    # created by the original migration). We keep the Enum in Python
    # for validation, but render it as plain text so SQLAlchemy does
    # not inject ``::accountsex`` casts.
    sex = Column(
        "gender",
        String(16),
        default=lambda: AccountSex.UNKNOWN.value,
        nullable=False,
    )
    # Which personal-channel template was last applied to this account.
    # Lets the UI show the chosen template (instead of "Без шаблона") and
    # lets a template edit auto-resync every account that uses it.
    personal_channel_template_id = Column(
        Integer,
        ForeignKey("personal_channel_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Telegram personal-channel id (``users.full.personal_channel_id``).
    # None means the account does not have a personal channel set up.
    personal_channel_id = Column(BigInteger, nullable=True)
    # Cached handle of the personal channel for display in the UI
    # without an extra round-trip.
    personal_channel_username = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, nullable=True)
    last_check_at = Column(DateTime, nullable=True)

    # GGR Health Score fields (16 factors)
    warmup_level = Column(Integer, default=0)  # Days of warmup (max ~30)
    daily_dm_count = Column(Integer, default=0)  # Messages sent today
    total_messages_sent = Column(Integer, default=0)
    daily_limit_used = Column(Float, default=0.0)  # Percentage 0-1
    folder = Column(String, default="new")  # new, warming, production, quarantine

    # Detailed health factors (stored as JSON for flexibility)
    health_factors = Column(JSON, nullable=True)
    # Computed health score (0-100)
    health_score = Column(Integer, nullable=True)

    # IDs of TelegramSources this account has successfully joined.
    # Used by neurocommenting to prefer accounts already in the group.
    joined_source_ids = Column(JSON, nullable=True, default=list)

    # IDs of TelegramSources where this account got USER_BANNED_IN_CHANNEL.
    # Neurocommenting skips these sources for this account automatically.
    banned_source_ids = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        default=list,
    )

    # Pool assignment for warmup: {"source_group_id": 5, "source_ids": [1,2,3]}
    # Set by POST /accounts/assign-warmup-pool; used in warmup.py setup phase.
    warmup_assignment = Column(JSON, nullable=True, default=None)

    # ── Phase-based warmup (new system) ─────────────────────────────────
    # null = not in phase warmup; 0=initial sleep; 1=profile done; 2=joins done;
    # 3=channel done; 4=completed. Advances automatically via tick_all().
    warmup_phase = Column(Integer, nullable=True, default=None)
    warmup_next_phase_at = Column(DateTime, nullable=True, default=None)
    warmup_language = Column(String(2), nullable=True, default=None)
    warmup_locked = Column(Boolean, default=False)
    warmup_pool_ids = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        default=list,
    )

    # Progressive channel-joining scheduler
    join_session_count = Column(Integer, default=0, nullable=False)
    join_last_session_at = Column(DateTime, nullable=True)
    # Assigned slice of the global pool for this account (set by distribute endpoint).
    # Only this account is responsible for these sources; other accounts get different slices.
    join_assigned_source_ids = Column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        default=list,
    )
    # Per-day progress for the episodic join scheduler (see channel_joiner_service).
    # A day's JOIN_PROGRESSION quota is spread across several randomly-timed
    # bursts instead of one uninterrupted run.
    join_day_date = Column(String(8), nullable=True)  # "YYYYMMDD"
    join_day_target = Column(Integer, nullable=True)
    join_day_joined = Column(Integer, default=0, nullable=False)
    join_next_episode_at = Column(DateTime, nullable=True)

    proxy = relationship("Proxy", back_populates="accounts")
    project = relationship("Project")

    __table_args__ = (
        Index("ix_accounts_status_gender", "status", "gender"),
    )

    @property
    def gender(self) -> str:
        return self.sex or AccountSex.UNKNOWN.value

    @gender.setter
    def gender(self, value: str | AccountSex | None) -> None:
        if isinstance(value, AccountSex):
            self.sex = value.value
        else:
            self.sex = value or AccountSex.UNKNOWN.value
