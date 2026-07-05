import os
from datetime import datetime, timedelta, time as time_type
from typing import AsyncGenerator

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Master(Base):
    __tablename__ = "masters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255))
    subscription_channel_id: Mapped[str | None] = mapped_column(String(255))
    subscription_channel_name: Mapped[str | None] = mapped_column(String(255))
    subscription_text: Mapped[str | None] = mapped_column(String(500))
    subscription_required: Mapped[bool] = mapped_column(Boolean, default=False)
    use_services: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    schedule_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_new_bookings: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_reminders: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_time: Mapped[str] = mapped_column(String(5), default="18:00")
    weekly_report_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_report_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Moscow")
    profile_link_warning_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)

    services: Mapped[list["Service"]] = relationship(back_populates="master", cascade="all, delete-orphan")
    clients: Mapped[list["Client"]] = relationship(back_populates="master", cascade="all, delete-orphan")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="master", cascade="all, delete-orphan")
    menu_buttons: Mapped[list["MenuButton"]] = relationship(back_populates="master", cascade="all, delete-orphan")
    blocked_times: Mapped[list["BlockedTime"]] = relationship(back_populates="master", cascade="all, delete-orphan")


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    master_id: Mapped[int] = mapped_column(Integer, ForeignKey("masters.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[str] = mapped_column(String(50), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    master: Mapped["Master"] = relationship(back_populates="services")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    master_id: Mapped[int] = mapped_column(Integer, ForeignKey("masters.id"), nullable=False, index=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    vk_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    master: Mapped["Master"] = relationship(back_populates="clients")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="client", cascade="all, delete-orphan")


class ClientProfile(Base):
    """Verified Telegram client identity shared between all master bots."""
    __tablename__ = "client_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("idx_bookings_master_date", "master_id", "date"),
        Index("idx_bookings_status_date", "status", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    master_id: Mapped[int] = mapped_column(Integer, ForeignKey("masters.id"), nullable=False)
    master_bot_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("master_bots.id"))
    client_id: Mapped[int] = mapped_column(Integer, ForeignKey("clients.id"), nullable=False)
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    time: Mapped[datetime] = mapped_column(Time, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(Time, nullable=False)  # Точное время окончания
    service_ids: Mapped[list] = mapped_column(JSON, default=list)
    service_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("services.id"))
    service_name: Mapped[str | None] = mapped_column(String(255))
    service_price_total: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="upcoming", index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    master_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    rescheduled_from_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("bookings.id"))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime)

    master: Mapped["Master"] = relationship(back_populates="bookings")
    client: Mapped["Client"] = relationship(back_populates="bookings")


class MenuButton(Base):
    __tablename__ = "menu_buttons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    master_id: Mapped[int] = mapped_column(Integer, ForeignKey("masters.id"), nullable=False)
    button_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)

    master: Mapped["Master"] = relationship(back_populates="menu_buttons")


class BlockedTime(Base):
    __tablename__ = "blocked_times"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    master_id: Mapped[int] = mapped_column(Integer, ForeignKey("masters.id"), nullable=False)
    date: Mapped[datetime] = mapped_column(Date, nullable=False)
    start_time: Mapped[datetime] = mapped_column(Time, nullable=False)
    end_time: Mapped[datetime] = mapped_column(Time, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    master: Mapped["Master"] = relationship(back_populates="blocked_times")


class BookingStatusHistory(Base):
    """Аудит изменений статуса записи"""
    __tablename__ = "booking_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(Integer, ForeignKey("bookings.id"), nullable=False, index=True)
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    changed_by: Mapped[str | None] = mapped_column(String(50))  # "client", "master", "system"
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SlotHold(Base):
    """Временная блокировка слота пока клиент заполняет форму"""
    __tablename__ = "slot_holds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    master_id: Mapped[int] = mapped_column(Integer, ForeignKey("masters.id"), nullable=False)
    date: Mapped[datetime] = mapped_column(Date, nullable=False)
    time: Mapped[datetime] = mapped_column(Time, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False)  # Telegram user_id или сессия
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MasterBot(Base):
    __tablename__ = "master_bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    master_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("masters.id"))
    master_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    pid: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)


class VkBot(Base):
    """Сообщество-бот ВКонтакте мастера. Зеркало MasterBot для канала VK."""
    __tablename__ = "vk_bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    master_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("masters.id"))
    master_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    group_name: Mapped[str | None] = mapped_column(String(255))
    owner_vk_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="creating")
    bot_type: Mapped[str] = mapped_column(String(20), default="client")  # "client" | "architect"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MasterVkProfile(Base):
    """VK-идентичность мастера в VK Архитекторе. Независима от TG-аккаунта."""
    __tablename__ = "master_vk_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vk_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    # Pseudo-telegram_id для связи с MasterBot/Subscription: -(vk_id)
    pseudo_telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    master_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("masters.id"), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    state: Mapped[str | None] = mapped_column(String(50))  # architect flow state
    state_data_json: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)


class VkClientProfile(Base):
    """Проверенная VK-идентичность клиента, общая для всех VK-ботов мастеров."""
    __tablename__ = "vk_client_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vk_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)


class VkClientRegistration(Base):
    """Durable two-step registration state for a VK community client."""
    __tablename__ = "vk_client_registrations"
    __table_args__ = (
        Index("ux_vk_client_registration_group_user", "group_id", "vk_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vk_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    step: Mapped[str] = mapped_column(String(20), default="phone", nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    master_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    master_bot_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("master_bots.id"))
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    price: Mapped[float] = mapped_column(Integer, default=250)
    payment_provider: Mapped[str] = mapped_column(String(50), default="manual")
    payment_id: Mapped[str | None] = mapped_column(String(255))
    telegram_payment_charge_id: Mapped[str | None] = mapped_column(String(255))
    provider_payment_charge_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    lifetime: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)


class ArchitectFunnelEvent(Base):
    """События воронки Architect Bot для расчёта конверсий."""
    __tablename__ = "architect_funnel_events"
    __table_args__ = (
        Index("idx_architect_funnel_type_user", "event_type", "telegram_id"),
        Index("idx_architect_funnel_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    master_bot_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("master_bots.id"), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class UtmCampaignGroup(Base):
    """Группы рекламных кампаний в супер-админке."""
    __tablename__ = "utm_campaign_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)


class UtmCampaign(Base):
    """Управляемые UTM-кампании для рекламных ссылок."""
    __tablename__ = "utm_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("utm_campaign_groups.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    placement_url: Mapped[str | None] = mapped_column(String(2048))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)


class ReferralCode(Base):
    """Permanent 4-digit referral code owned by an Architect Bot user."""
    __tablename__ = "referral_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(4), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ReferralApplication(Base):
    """A one-time promo code application by a referred user."""
    __tablename__ = "referral_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_id: Mapped[int] = mapped_column(Integer, ForeignKey("referral_codes.id"), nullable=False, index=True)
    referrer_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    referred_telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="applied", index=True)
    subscription_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("subscriptions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime)


class ShortUrl(Base):
    """Короткие ссылки для меню бота"""
    __tablename__ = "short_urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True, nullable=False)
    original_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./master_booking.db")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine_kwargs = {"echo": False, "pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    # SQLite-specific option; asyncpg/psycopg reject check_same_thread.
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(DATABASE_URL, **engine_kwargs)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_master_columns(conn)
        await _add_missing_booking_columns(conn)
        await _add_missing_subscription_payment_columns(conn)
        await _add_missing_master_bot_columns(conn)
        await _add_missing_client_columns(conn)
        await _add_missing_utm_campaign_columns(conn)
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_clients_master_id ON clients (master_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_clients_telegram_id ON clients (telegram_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_clients_vk_id ON clients (vk_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_vk_bots_master_telegram_id ON vk_bots (master_telegram_id)"))
        await _add_missing_vk_bot_columns(conn)
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_master_vk_profiles_vk_id ON master_vk_profiles (vk_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_slot_holds_expires_at ON slot_holds (expires_at)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_master_bots_master_telegram_id ON master_bots (master_telegram_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_master_bots_master_id ON master_bots (master_id)"))
    await _backfill_master_bot_profiles()
    await _seed_default_utm_campaigns()


DEFAULT_UTM_TARGET = "https://architektor.online/services/"

DEFAULT_UTM_CAMPAIGNS = [
    ("organic", "Органика сайта", DEFAULT_UTM_TARGET),
    ("pikabu", "Пикабу", DEFAULT_UTM_TARGET),
    ("vc", "vc.ru", DEFAULT_UTM_TARGET),
    ("dzen", "Дзен", DEFAULT_UTM_TARGET),
    ("habr", "Хабр", DEFAULT_UTM_TARGET),
    ("ad1", "Реклама 1", DEFAULT_UTM_TARGET),
    ("ad2", "Реклама 2", DEFAULT_UTM_TARGET),
    ("ad3", "Реклама 3", DEFAULT_UTM_TARGET),
]


async def _seed_default_utm_campaigns() -> None:
    """Create built-in UTM campaigns once without overwriting admin edits."""
    from sqlalchemy import select

    async with async_session_maker() as session:
        changed = False
        for source, name, target_url in DEFAULT_UTM_CAMPAIGNS:
            campaign = (await session.execute(
                select(UtmCampaign).where(UtmCampaign.source == source)
            )).scalar_one_or_none()
            if campaign:
                continue
            session.add(UtmCampaign(
                source=source,
                name=name,
                target_url=target_url,
                active=True,
            ))
            changed = True
        if changed:
            await session.commit()


async def _add_missing_utm_campaign_columns(conn) -> None:
    """Add editable placement links to existing UTM campaign tables."""
    from sqlalchemy import inspect, text

    columns = await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("utm_campaigns")}
    )
    if "placement_url" not in columns:
        await conn.execute(text("ALTER TABLE utm_campaigns ADD COLUMN placement_url VARCHAR(2048)"))
    if "group_id" not in columns:
        await conn.execute(text("ALTER TABLE utm_campaigns ADD COLUMN group_id INTEGER REFERENCES utm_campaign_groups(id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_utm_campaigns_group_id ON utm_campaigns (group_id)"))


async def _add_missing_master_columns(conn) -> None:
    """Add recently introduced master settings to existing databases."""
    from sqlalchemy import inspect, text

    columns = await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("masters")}
    )
    definitions = {
        "notify_new_bookings": "BOOLEAN DEFAULT 1",
        "notify_reminders": "BOOLEAN DEFAULT 1",
        "reminder_time": "VARCHAR(5) DEFAULT '18:00'",
        "weekly_report_enabled": "BOOLEAN DEFAULT 0",
        "weekly_report_sent_at": "TIMESTAMP",
        "timezone": "VARCHAR(50) DEFAULT 'Europe/Moscow'",
        "profile_link_warning_dismissed": "BOOLEAN DEFAULT 0",
    }
    for column_name, definition in definitions.items():
        if column_name not in columns:
            await conn.execute(text(f"ALTER TABLE masters ADD COLUMN {column_name} {definition}"))


async def _add_missing_subscription_payment_columns(conn) -> None:
    """Add payment audit fields for databases created before Telegram invoices."""
    from sqlalchemy import inspect, text

    columns = await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("subscriptions")}
    )
    definitions = {
        "telegram_payment_charge_id": "VARCHAR(255)",
        "provider_payment_charge_id": "VARCHAR(255)",
        "master_bot_id": "INTEGER REFERENCES master_bots(id)",
        "lifetime": "BOOLEAN DEFAULT 0",
    }
    for column_name, definition in definitions.items():
        if column_name not in columns:
            await conn.execute(text(f"ALTER TABLE subscriptions ADD COLUMN {column_name} {definition}"))


async def _add_missing_vk_bot_columns(conn) -> None:
    """Add bot_type column introduced with the VK Architect feature."""
    from sqlalchemy import inspect, text

    columns = await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("vk_bots")}
    )
    if "bot_type" not in columns:
        await conn.execute(text("ALTER TABLE vk_bots ADD COLUMN bot_type VARCHAR(20) DEFAULT 'client'"))


async def _add_missing_client_columns(conn) -> None:
    """Add VK identity to client cards created before the VK channel."""
    from sqlalchemy import inspect, text

    columns = await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("clients")}
    )
    if "vk_id" not in columns:
        await conn.execute(text("ALTER TABLE clients ADD COLUMN vk_id BIGINT"))


async def _add_missing_master_bot_columns(conn) -> None:
    """Add lifecycle timestamps without changing the original bot creation date."""
    from sqlalchemy import inspect, text

    columns = await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("master_bots")}
    )
    if "master_id" not in columns:
        await conn.execute(text("ALTER TABLE master_bots ADD COLUMN master_id INTEGER REFERENCES masters(id)"))
    if "trial_started_at" not in columns:
        await conn.execute(text("ALTER TABLE master_bots ADD COLUMN trial_started_at TIMESTAMP"))


async def _backfill_master_bot_profiles() -> None:
    """Ensure every bot points to its own master profile.

    Legacy schema stored several bots under one Master row keyed by owner telegram_id.
    New schema links each MasterBot to a dedicated master_id. Existing extra bots are
    split into separate profiles with cloned settings, services, menu buttons, blocked
    times, and bot-scoped bookings.
    """
    from copy import deepcopy
    from sqlalchemy import select

    async with async_session_maker() as session:
        bots = (await session.execute(
            select(MasterBot).order_by(MasterBot.master_telegram_id.asc(), MasterBot.created_at.asc(), MasterBot.id.asc())
        )).scalars().all()
        if not bots:
            return

        bots_by_owner: dict[int, list[MasterBot]] = {}
        for bot in bots:
            bots_by_owner.setdefault(bot.master_telegram_id, []).append(bot)

        changed = False

        async def clone_master_profile(source: Master, owner_telegram_id: int) -> tuple[Master, dict[int, int]]:
            nonlocal changed
            clone = Master(
                name=source.name,
                avatar_url=source.avatar_url,
                telegram_id=None,
                telegram_username=source.telegram_username,
                subscription_channel_id=source.subscription_channel_id,
                subscription_channel_name=source.subscription_channel_name,
                subscription_text=source.subscription_text,
                subscription_required=source.subscription_required,
                use_services=source.use_services,
                interval_minutes=source.interval_minutes,
                schedule_json=deepcopy(source.schedule_json or {}),
                is_demo=False,
                notify_new_bookings=source.notify_new_bookings,
                notify_reminders=source.notify_reminders,
                reminder_time=source.reminder_time,
                weekly_report_enabled=source.weekly_report_enabled,
                weekly_report_sent_at=source.weekly_report_sent_at,
                timezone=source.timezone,
                profile_link_warning_dismissed=source.profile_link_warning_dismissed,
            )
            session.add(clone)
            await session.flush()

            service_map: dict[int, int] = {}
            source_services = (await session.execute(
                select(Service).where(Service.master_id == source.id).order_by(Service.sort_order.asc(), Service.id.asc())
            )).scalars().all()
            for service in source_services:
                new_service = Service(
                    master_id=clone.id,
                    name=service.name,
                    price=service.price,
                    duration_minutes=service.duration_minutes,
                    active=service.active,
                    sort_order=service.sort_order,
                )
                session.add(new_service)
                await session.flush()
                service_map[service.id] = new_service.id

            source_buttons = (await session.execute(
                select(MenuButton).where(MenuButton.master_id == source.id).order_by(MenuButton.id.asc())
            )).scalars().all()
            for button in source_buttons:
                session.add(MenuButton(
                    master_id=clone.id,
                    button_type=button.button_type,
                    content_json=deepcopy(button.content_json or {}),
                    active=button.active,
                ))

            source_blocks = (await session.execute(
                select(BlockedTime).where(BlockedTime.master_id == source.id).order_by(BlockedTime.date.asc(), BlockedTime.id.asc())
            )).scalars().all()
            for blocked in source_blocks:
                session.add(BlockedTime(
                    master_id=clone.id,
                    date=blocked.date,
                    start_time=blocked.start_time,
                    end_time=blocked.end_time,
                    reason=blocked.reason,
                ))

            changed = True
            return clone, service_map

        for owner_telegram_id, owner_bots in bots_by_owner.items():
            legacy_master = (await session.execute(
                select(Master).where(Master.telegram_id == owner_telegram_id).order_by(Master.id.asc())
            )).scalar_one_or_none()

            if not legacy_master:
                legacy_master = Master(
                    telegram_id=owner_telegram_id,
                    name="Мастер",
                    is_demo=False,
                    use_services=False,
                    interval_minutes=60,
                    schedule_json=deepcopy(DEFAULT_SCHEDULE),
                )
                session.add(legacy_master)
                await session.flush()
                changed = True

            primary_bot = owner_bots[0]
            if primary_bot.master_id != legacy_master.id:
                primary_bot.master_id = legacy_master.id
                changed = True

            for extra_bot in owner_bots[1:]:
                if extra_bot.master_id:
                    continue
                clone_master, service_map = await clone_master_profile(legacy_master, owner_telegram_id)
                extra_bot.master_id = clone_master.id

                bot_bookings = (await session.execute(
                    select(Booking).where(
                        Booking.master_bot_id == extra_bot.id,
                        Booking.master_id == legacy_master.id,
                    ).order_by(Booking.id.asc())
                )).scalars().all()
                client_map: dict[int, int] = {}
                for booking in bot_bookings:
                    if booking.client_id not in client_map:
                        client = await session.get(Client, booking.client_id)
                        if client:
                            new_client = Client(
                                master_id=clone_master.id,
                                telegram_id=client.telegram_id,
                                name=client.name,
                                phone=client.phone,
                            )
                            session.add(new_client)
                            await session.flush()
                            client_map[client.id] = new_client.id
                    booking.master_id = clone_master.id
                    if booking.client_id in client_map:
                        booking.client_id = client_map[booking.client_id]
                    if booking.service_id in service_map:
                        booking.service_id = service_map[booking.service_id]
                    if booking.service_ids:
                        booking.service_ids = [service_map.get(service_id, service_id) for service_id in booking.service_ids]
                changed = True

        if changed:
            await session.commit()


async def _add_missing_booking_columns(conn) -> None:
    """Add the source bot reference used for multi-bot client notifications."""
    from sqlalchemy import inspect, text

    columns = await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("bookings")}
    )
    if "master_bot_id" not in columns:
        await conn.execute(text("ALTER TABLE bookings ADD COLUMN master_bot_id INTEGER REFERENCES master_bots(id)"))
    if "reminder_sent_at" not in columns:
        await conn.execute(text("ALTER TABLE bookings ADD COLUMN reminder_sent_at TIMESTAMP"))
    if "service_price_total" not in columns:
        await conn.execute(text("ALTER TABLE bookings ADD COLUMN service_price_total INTEGER"))


DEFAULT_SCHEDULE = {
    "booking_days": 90,
    "days": [
        {"day": "Пн", "active": True, "work_start": "09:00", "work_end": "18:00", "break_start": "13:00", "break_end": "14:00"},
        {"day": "Вт", "active": True, "work_start": "09:00", "work_end": "18:00", "break_start": "13:00", "break_end": "14:00"},
        {"day": "Ср", "active": True, "work_start": "09:00", "work_end": "18:00", "break_start": "13:00", "break_end": "14:00"},
        {"day": "Чт", "active": True, "work_start": "09:00", "work_end": "18:00", "break_start": "13:00", "break_end": "14:00"},
        {"day": "Пт", "active": True, "work_start": "09:00", "work_end": "18:00", "break_start": "13:00", "break_end": "14:00"},
        {"day": "Сб", "active": False, "work_start": "10:00", "work_end": "16:00", "break_start": "13:00", "break_end": "14:00"},
        {"day": "Вс", "active": False, "work_start": "10:00", "work_end": "16:00", "break_start": "13:00", "break_end": "14:00"},
    ],
    "exceptions": []
}


DEMO_MENU_BUTTONS = {
    "price": {
        "active": True,
        "content": {
            "items": [
                {"name": "Стрижка и укладка", "price": "1500 ₽"},
                {"name": "Маникюр с покрытием", "price": "2000 ₽"},
                {"name": "Оформление бровей", "price": "800 ₽"},
            ]
        },
    },
    "faq": {
        "active": True,
        "content": {
            "items": [
                {"question": "Можно ли перенести запись?", "answer": "В реальном боте клиент пишет мастеру, а мастер переносит запись в календаре."},
                {"question": "Приходит ли уведомление?", "answer": "В реальном режиме уведомление получает и мастер, и клиент."},
            ]
        },
    },
    "address": {
        "active": True,
        "content": {
            "text": "📍 Демо-студия\nЕкатеринбург, ул. Примерная, 10\n\nЭто тестовый адрес для просмотра клиентского меню.",
            "photo": "",
        },
    },
    "portfolio": {
        "active": True,
        "content": {
            "photos": [
                "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=900&q=80",
                "https://images.unsplash.com/photo-1633681926022-84c23e8cb2d6?auto=format&fit=crop&w=900&q=80",
                "https://images.unsplash.com/photo-1600948836101-f9ffda59d250?auto=format&fit=crop&w=900&q=80",
            ]
        },
    },
    "custom": {
        "active": True,
        "content": {
            "custom_buttons": [
                {
                    "name": "Правила записи",
                    "icon": "✨",
                    "active": True,
                    "texts": [
                        "Пожалуйста, приходите за 5 минут до записи. Если планы изменились, перенесите или отмените запись заранее."
                    ],
                    "links": [
                        {"text": "Написать мастеру", "url": "https://t.me/SoftwareArchitects_bot"}
                    ],
                    "photos": [],
                }
            ]
        },
    },
}


DEMO_MASTER_ID = 999
DEMO_MASTER_TELEGRAM_ID = 999
PLACEHOLDER_CUSTOM_BUTTON_NAMES = {"Напишите своё название", "Название кнопки", "Информация"}
DEMO_AVATAR_URL = "/demo-avatar.jpg"


def _apply_demo_identity(master: Master) -> bool:
    """Keep the read-only demo master on its stable synthetic identity."""
    changed = False
    if master.telegram_id != DEMO_MASTER_TELEGRAM_ID:
        master.telegram_id = DEMO_MASTER_TELEGRAM_ID
        changed = True
    if master.name != "Анна, демо-мастер":
        master.name = "Анна, демо-мастер"
        changed = True
    target_avatar = DEMO_AVATAR_URL
    if master.avatar_url != target_avatar:
        master.avatar_url = target_avatar
        changed = True
    return changed


def _sanitize_demo_menu_button(button: MenuButton) -> bool:
    """Remove old placeholder custom demo items without touching real demo content."""
    if button.button_type != "custom" or not isinstance(button.content_json, dict):
        return False

    content = dict(button.content_json)
    nested = content.get("content") if isinstance(content.get("content"), dict) else None
    holder = nested if nested is not None else content
    items = holder.get("custom_buttons")
    if not isinstance(items, list):
        return False

    had_placeholder = False
    cleaned = []
    for item in items:
        if (item.get("name") or "").strip() in PLACEHOLDER_CUSTOM_BUTTON_NAMES:
            had_placeholder = True
            continue
        cleaned.append(item)
    if not cleaned:
        cleaned = list(DEMO_MENU_BUTTONS["custom"]["content"]["custom_buttons"])
    if not had_placeholder and len(cleaned) == len(items):
        return False
    holder["custom_buttons"] = cleaned
    if nested is not None:
        content["content"] = holder
    button.content_json = content
    button.active = bool(cleaned)
    return True


async def get_demo_master(db: AsyncSession) -> Master:
    """Find or create demo master. Returns demo master with is_demo=True."""
    from sqlalchemy import select

    # Try to find existing demo master
    result = await db.execute(select(Master).where(Master.is_demo == True))
    demo_master = result.scalar_one_or_none()

    if demo_master:
        if _apply_demo_identity(demo_master):
            await db.commit()
        return demo_master

    # Check if Master.id=1 exists and is not demo
    result = await db.execute(select(Master).where(Master.id == 1))
    master_1 = result.scalar_one_or_none()

    if master_1 and not master_1.is_demo:
        # Create demo master with DEMO_MASTER_ID
        demo_master = Master(
            id=DEMO_MASTER_ID,
            name="Анна, демо-мастер",
            avatar_url=DEMO_AVATAR_URL,
            use_services=True,
            interval_minutes=60,
            schedule_json=DEFAULT_SCHEDULE,
            telegram_id=DEMO_MASTER_TELEGRAM_ID,
            is_demo=True,
        )
        db.add(demo_master)
        await db.flush()

        # Add demo services
        demo_services = [
            Service(master_id=DEMO_MASTER_ID, name="💇 Стрижка", price="1500 ₽", duration_minutes=60, sort_order=1),
            Service(master_id=DEMO_MASTER_ID, name="💅 Маникюр", price="2000 ₽", duration_minutes=90, sort_order=2),
            Service(master_id=DEMO_MASTER_ID, name="👁 Брови", price="800 ₽", duration_minutes=30, sort_order=3),
        ]
        for svc in demo_services:
            db.add(svc)
        await db.commit()
        await db.refresh(demo_master)

        # Ensure demo content
        await ensure_demo_content(db, demo_master)
        return demo_master

    # If Master.id=1 is free - create demo master with id=1
    demo_master = Master(
        id=1,
        name="Анна, демо-мастер",
        avatar_url=DEMO_AVATAR_URL,
        use_services=True,
        interval_minutes=60,
        schedule_json=DEFAULT_SCHEDULE,
        telegram_id=DEMO_MASTER_TELEGRAM_ID,
        is_demo=True,
    )
    db.add(demo_master)
    await db.flush()

    # Add demo services
    demo_services = [
        Service(master_id=1, name="💇 Стрижка", price="1500 ₽", duration_minutes=60, sort_order=1),
        Service(master_id=1, name="💅 Маникюр", price="2000 ₽", duration_minutes=90, sort_order=2),
        Service(master_id=1, name="👁 Брови", price="800 ₽", duration_minutes=30, sort_order=3),
    ]
    for svc in demo_services:
        db.add(svc)
    await db.commit()
    await db.refresh(demo_master)

    # Ensure demo content
    await ensure_demo_content(db, demo_master)
    return demo_master

async def seed_master(db: AsyncSession):
    from sqlalchemy import select

    # Ищем существующего демо-мастера
    result = await db.execute(select(Master).where(Master.is_demo == True))
    demo_master = result.scalar_one_or_none()

    # Если демо-мастер уже есть, обновляем его данные
    if demo_master:
        if _apply_demo_identity(demo_master):
            await db.commit()
        await ensure_demo_content(db, demo_master)
        return

    # Если Master.id=1 существует и не демо — не трогаем его, создаём отдельного демо-мастера
    result = await db.execute(select(Master).where(Master.id == 1))
    master_1 = result.scalar_one_or_none()

    if master_1 and not master_1.is_demo:
        # Создаём нового демо-мастера с отдельным ID
        demo_master = Master(
            id=DEMO_MASTER_ID,
            name="Анна, демо-мастер",
            avatar_url=DEMO_AVATAR_URL,
            use_services=True,
            interval_minutes=60,
            schedule_json=DEFAULT_SCHEDULE,
            telegram_id=DEMO_MASTER_TELEGRAM_ID,
            is_demo=True,
        )
        db.add(demo_master)
        await db.flush()

        # Демо-услуги
        demo_services = [
            Service(master_id=DEMO_MASTER_ID, name="💇 Стрижка", price="1500 ₽", duration_minutes=60, sort_order=1),
            Service(master_id=DEMO_MASTER_ID, name="💅 Маникюр", price="2000 ₽", duration_minutes=90, sort_order=2),
            Service(master_id=DEMO_MASTER_ID, name="👁 Брови", price="800 ₽", duration_minutes=30, sort_order=3),
        ]
        for svc in demo_services:
            db.add(svc)
        await db.commit()
        await db.refresh(demo_master)
        await ensure_demo_content(db, demo_master)
        return

    # Если Master.id=1 не существует или он демо — используем его как демо-мастера
    if not master_1:
        master_1 = Master(
            id=1,
            name="Анна, демо-мастер",
            avatar_url=DEMO_AVATAR_URL,
            use_services=True,
            interval_minutes=60,
            schedule_json=DEFAULT_SCHEDULE,
            telegram_id=DEMO_MASTER_TELEGRAM_ID,
            is_demo=True,
        )
        db.add(master_1)
        await db.flush()

        # Демо-услуги
        demo_services = [
            Service(master_id=1, name="💇 Стрижка", price="1500 ₽", duration_minutes=60, sort_order=1),
            Service(master_id=1, name="💅 Маникюр", price="2000 ₽", duration_minutes=90, sort_order=2),
            Service(master_id=1, name="👁 Брови", price="800 ₽", duration_minutes=30, sort_order=3),
        ]
        for svc in demo_services:
            db.add(svc)
        await db.commit()
        await db.refresh(master_1)

    await ensure_demo_content(db, master_1)


async def ensure_demo_content(db: AsyncSession, master: Master) -> bool:
    """Keep the architect demo rich, while never touching real masters.
    Returns True if changes were made, False otherwise.
    Raises ValueError if master is not a demo master.
    """
    from sqlalchemy import func, select

    if not master.is_demo:
        raise ValueError("ensure_demo_content can only be called on demo masters (is_demo=True)")

    changed = False
    changed = _apply_demo_identity(master) or changed
    if not master.schedule_json:
        master.schedule_json = DEFAULT_SCHEDULE
        changed = True

    services_count = await db.scalar(select(func.count(Service.id)).where(Service.master_id == master.id))
    if not services_count:
        for svc in [
            Service(master_id=master.id, name="💇 Стрижка", price="1500 ₽", duration_minutes=60, sort_order=1),
            Service(master_id=master.id, name="💅 Маникюр", price="2000 ₽", duration_minutes=90, sort_order=2),
            Service(master_id=master.id, name="👁 Брови", price="800 ₽", duration_minutes=30, sort_order=3),
        ]:
            db.add(svc)
        changed = True

    buttons_count = await db.scalar(select(func.count(MenuButton.id)).where(MenuButton.master_id == master.id))
    if not buttons_count:
        for button_type, payload in DEMO_MENU_BUTTONS.items():
            db.add(MenuButton(
                master_id=master.id,
                button_type=button_type,
                active=payload["active"],
                content_json=payload["content"],
            ))
            changed = True
    else:
        existing_buttons = (await db.execute(
            select(MenuButton).where(MenuButton.master_id == master.id)
        )).scalars().all()
        for button in existing_buttons:
            changed = _sanitize_demo_menu_button(button) or changed

    demo_people = [
        ("Мария Тестовая", "+7 900 000-00-01", "Подровнять кончики."),
        ("Анна Смирнова", "+7 900 000-00-02", "Можно немного раньше, если появится окно."),
        ("Елена Кузнецова", "+7 900 000-00-03", "Первый визит."),
        ("Ольга Попова", "+7 900 000-00-04", "Без дополнительных пожеланий."),
        ("Ирина Соколова", "+7 900 000-00-05", "Напишите, пожалуйста, если изменится время."),
    ]
    clients = []
    for name, phone, _ in demo_people:
        result = await db.execute(select(Client).where(Client.master_id == master.id, Client.name == name))
        client = result.scalar_one_or_none()
        if not client:
            client = Client(master_id=master.id, name=name, phone=phone)
            db.add(client)
            await db.flush()
            changed = True
        clients.append(client)

    start_date = datetime.utcnow().date()
    end_date = start_date + timedelta(days=89)
    existing_rows = await db.execute(
        select(Booking.date).where(
            Booking.master_id == master.id,
            Booking.date >= start_date,
            Booking.date <= end_date,
            Booking.status.in_(["upcoming", "confirmed"]),
        )
    )
    booked_dates = {row[0] for row in existing_rows.all()}
    services = (await db.execute(select(Service).where(Service.master_id == master.id).order_by(Service.sort_order))).scalars().all()
    demo_times = [time_type(10, 0), time_type(12, 30), time_type(16, 0)]
    for day_offset in range(90):
        current_date = start_date + timedelta(days=day_offset)
        if current_date in booked_dates:
            continue
        service = services[day_offset % len(services)] if services else None
        client = clients[day_offset % len(clients)]
        comment = demo_people[day_offset % len(demo_people)][2]
        start_time = demo_times[day_offset % len(demo_times)]
        duration = service.duration_minutes if service else 60
        end_minutes = start_time.hour * 60 + start_time.minute + duration
        db.add(Booking(
            master_id=master.id,
            client_id=client.id,
            date=current_date,
            time=start_time,
            ends_at=time_type(end_minutes // 60, end_minutes % 60),
            duration_minutes=duration,
            service_id=service.id if service else None,
            service_ids=[service.id] if service else [],
            service_name=service.name if service else "Демо-услуга",
            status="upcoming",
            comment=comment,
        ))
        changed = True

    if changed:
        await db.commit()
        return True
    return False
