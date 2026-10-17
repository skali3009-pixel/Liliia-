"""One durable delivery and latest response per campaign/person."""
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class SurveyResponse(Base):
    __tablename__ = 'survey_responses'
    campaign: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    delivery: Mapped[str] = mapped_column(String(24), default='sending', nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(80), nullable=True)
    choice: Mapped[str | None] = mapped_column(String(24), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment_prompt_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comment_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
