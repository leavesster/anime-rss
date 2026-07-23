from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from anime_rss.infrastructure.database import Base, UTCDateTime
from anime_rss.kernel.time import utc_now


class SeasonalDecisionRecord(Base):
    __tablename__ = "seasonal_decisions"

    bangumi_id: Mapped[int] = mapped_column(primary_key=True)
    decision: Mapped[str] = mapped_column(String(24), default="dismissed")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
