from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, JSON, UniqueConstraint, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from contextlib import contextmanager

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    name = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(String, default='athlete')  # athlete, trainer, developer
    notifications_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserState(Base):
    __tablename__ = 'user_states'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    chat_id = Column(Integer)
    bot_id = Column(Integer)
    state = Column(String)
    data = Column(JSON)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class FlightHistory(Base):
    __tablename__ = 'flight_history'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, nullable=False)
    schedule_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Training(Base):
    __tablename__ = 'trainings'
    __table_args__ = (
        UniqueConstraint('telegram_id', 'date', 'time', name='uq_training_user_date_time'),
    )

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, nullable=False)
    athlete_name = Column(String, nullable=False)
    date = Column(String, nullable=False)  # DD.MM format
    time = Column(String, nullable=False)  # HH:MM format
    yandex_folder_path = Column(String)
    yandex_folder_url = Column(String)
    videos_uploaded = Column(Boolean, default=False)
    reminder_sent = Column(Boolean, default=False)
    check_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

class SundayPoll(Base):
    __tablename__ = 'sunday_polls'
    __table_args__ = (
        UniqueConstraint('poll_date', 'telegram_id', name='uq_poll_batch_user'),
    )

    id = Column(Integer, primary_key=True)
    poll_date = Column(DateTime, nullable=False)
    telegram_id = Column(Integer, nullable=False)
    will_fly = Column(Boolean)
    schedule_text = Column(Text)
    comment = Column(Text)
    responded_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

class TrainerMessage(Base):
    __tablename__ = 'trainer_messages'

    id = Column(Integer, primary_key=True)
    batch_id = Column(String)
    message_text = Column(Text, nullable=False)
    parsed_data = Column(JSON)
    sent_to_forum = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class VideoCheck(Base):
    __tablename__ = 'video_checks'

    id = Column(Integer, primary_key=True)
    training_id = Column(Integer, nullable=False)
    check_date = Column(DateTime, default=datetime.utcnow)
    videos_count = Column(Integer, default=0)
    notification_sent = Column(Boolean, default=False)

class ErrorLog(Base):
    __tablename__ = 'error_logs'

    id = Column(Integer, primary_key=True)
    error_type = Column(String, nullable=False)
    error_message = Column(Text, nullable=False)
    traceback = Column(Text)
    context = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

class BotGroupMessage(Base):
    __tablename__ = 'bot_group_messages'

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, nullable=False)  # Telegram message_id in the group
    chat_id = Column(Integer, nullable=False)
    text_preview = Column(String, default="")  # First 100 chars for display
    created_at = Column(DateTime, default=datetime.utcnow)

class ProcessedEvent(Base):
    __tablename__ = 'processed_events'

    id = Column(Integer, primary_key=True)
    event_key = Column(String, unique=True, nullable=False)
    event_type = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

engine = create_engine(
    'sqlite:///bot.db',
    echo=False,
    connect_args={"timeout": 30, "check_same_thread": False},
)

@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(user_states)").fetchall()}
        if "chat_id" not in columns:
            conn.exec_driver_sql("ALTER TABLE user_states ADD COLUMN chat_id INTEGER")
        if "bot_id" not in columns:
            conn.exec_driver_sql("ALTER TABLE user_states ADD COLUMN bot_id INTEGER")
        
        user_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()}
        if "notifications_enabled" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN notifications_enabled BOOLEAN DEFAULT 1")

        trainer_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(trainer_messages)").fetchall()}
        if "batch_id" not in trainer_columns:
            conn.exec_driver_sql("ALTER TABLE trainer_messages ADD COLUMN batch_id VARCHAR")
