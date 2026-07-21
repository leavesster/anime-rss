from datetime import datetime

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.ids import new_id
from anime_rss.kernel.time import utc_now


class AdminAccountRecord(Base):
    __tablename__ = "sys_admin_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class AdminSessionRecord(Base):
    __tablename__ = "sys_admin_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class InstanceSettingsRecord(Base):
    __tablename__ = "sys_instance_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default="default")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Shanghai")
    interface_language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    missing_episode_grace_hours: Mapped[int] = mapped_column(Integer, default=24)
    setup_completed_steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    setup_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
