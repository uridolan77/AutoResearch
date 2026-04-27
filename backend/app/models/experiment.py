import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import Decision, ExperimentStatus

# Single source of truth for rejection comment max length.
# Kept in sync with the String(N) column definition below.
REJECTION_COMMENT_MAX_LEN = 500


def _uuid() -> str:
    return str(uuid.uuid4())


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("session_id", "iteration", name="uq_experiments_session_iteration"),
        Index("ix_experiments_session_diffhash", "session_id", "diff_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), index=True
    )
    iteration: Mapped[int] = mapped_column(Integer)

    parent_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    experiment_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[ExperimentStatus] = mapped_column(
        Enum(ExperimentStatus), default=ExperimentStatus.pending, index=True
    )

    diff_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    validation_attempts: Mapped[int] = mapped_column(Integer, default=0)

    score_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    tokens_used: Mapped[int] = mapped_column(Integer, default=0)

    decision: Mapped[Decision | None] = mapped_column(Enum(Decision), nullable=True)
    rejection_comment: Mapped[str | None] = mapped_column(String(REJECTION_COMMENT_MAX_LEN), nullable=True)

    kept: Mapped[bool] = mapped_column(Boolean, default=False)
    worktree_pruned: Mapped[bool] = mapped_column(Boolean, default=False)
    worktree_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )

    session = relationship("Session", back_populates="experiments")
    runs = relationship("Run", back_populates="experiment", cascade="all, delete-orphan")
