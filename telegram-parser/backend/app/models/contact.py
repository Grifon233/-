from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from datetime import datetime
from app.db.base_class import Base

class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("project_id", "telegram_id", name="uq_contacts_project_telegram_id"),)

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("contact_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    telegram_id = Column(String, index=True, nullable=True) # can be empty if only username is known
    username = Column(String, index=True, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    
    source = Column(String, nullable=True) # where it was parsed from
    is_processed = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, default=1, index=True)


class ContactGroup(Base):
    __tablename__ = "contact_groups"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_contact_groups_project_name"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, default=1, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
