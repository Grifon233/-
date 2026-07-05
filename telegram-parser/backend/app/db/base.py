from app.db.base_class import Base
from app.models.proxy import Proxy
from app.models.account import Account
from app.models.contact import Contact, ContactGroup
from app.models.template import MessageTemplate
from app.models.campaign import Campaign, MessageLog
from app.models.parsing import ParsingTask
from app.models.external_parser import ExternalParserRun
from app.models.reaction_task import ReactionTask
from app.models.group_task import GroupTask
from app.models.ai_settings import AISettings
from app.models.project import Project
from app.models.telegram_source import TelegramSource, TelegramSourceGroup
from app.models.comment_task import CommentTask, CommentDraft, CommentLog, CommentTaskSourceState
from app.models.personal_channel_template import (
    PersonalChannelTemplate,
    PersonalChannelTemplatePost,
)
