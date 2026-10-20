from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    invite_code: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    memberships: Mapped[list["Membership"]] = relationship(back_populates="league")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("league_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("leagues.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    league: Mapped["League"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(back_populates="memberships")


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("leagues.id"), nullable=False, index=True
    )
    creator_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    resolved_outcome: Mapped[str | None] = mapped_column(String(8), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    picks: Mapped[list["Pick"]] = relationship(back_populates="prediction")


class Pick(Base):
    __tablename__ = "picks"
    __table_args__ = (UniqueConstraint("prediction_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        ForeignKey("predictions.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    stake: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    prediction: Mapped["Prediction"] = relationship(back_populates="picks")
