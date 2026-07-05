from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base_class import Base
from app.db.encrypted_type import EncryptedString

class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True, index=True)
    scheme = Column(String, default="socks5")  # socks5, http
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String, nullable=True)
    password = Column(EncryptedString, nullable=True)
    is_active = Column(Boolean, default=True)
    last_checked_at = Column(DateTime, nullable=True)
    response_time_ms = Column(Integer, nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, default=1, index=True)

    # ── Vendor / lifecycle tracking ────────────────────────────────────
    # ``source`` describes how the proxy was added:
    # * ``manual``   — operator typed it in
    # * ``pasted``   — bulk paste textarea
    # * ``vendor``   — bought from a provider (proxy6.net, webshare)
    # * ``tdata``    — extracted from a tdata import
    source = Column(String, default="manual", nullable=False)
    # Vendor-issued id (e.g. proxy6.net's numeric id). Together with
    # ``vendor_name`` it forms the unique key we use to re-import a
    # list owned by the operator.
    vendor_name = Column(String, nullable=True)
    vendor_proxy_id = Column(String, nullable=True)
    # ISO country code (``us`` / ``nl`` / …) the proxy is geo-located
    # to. Used by the gender/country filters.
    country = Column(String, nullable=True)
    # Expiration timestamp. The UI shows a countdown and turns the
    # row red two days before ``expires_at``.
    expires_at = Column(DateTime, nullable=True)
    # Free-form note column (operator reminder, e.g. "from 5/6 sale").
    note = Column(String, nullable=True)
    use_for_accounts = Column(Boolean, default=True, nullable=False)
    max_accounts = Column(Integer, nullable=True, default=3)

    accounts = relationship("Account", back_populates="proxy")
