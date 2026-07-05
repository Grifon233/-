from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class PersonalChannelTemplate(Base):
    __tablename__ = "personal_channel_templates"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    channel_title = Column(String(128), nullable=False)
    channel_about = Column(String(255), nullable=True)
    channel_avatar_mode = Column(String(32), nullable=False, default="none")
    channel_avatar_path = Column(String(512), nullable=True)
    channel_avatar_filename = Column(String(255), nullable=True)
    channel_avatar_mime_type = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    posts = relationship(
        "PersonalChannelTemplatePost",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="PersonalChannelTemplatePost.position",
    )


class PersonalChannelTemplatePost(Base):
    __tablename__ = "personal_channel_template_posts"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("personal_channel_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=1)
    text = Column(Text, nullable=True)
    image_path = Column(String(512), nullable=True)
    image_filename = Column(String(255), nullable=True)
    image_mime_type = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    template = relationship("PersonalChannelTemplate", back_populates="posts")
