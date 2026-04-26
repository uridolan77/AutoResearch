import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import ReviewMode, SessionStatus


def _uuid() -> str:
    return str(uuid.uuid4())


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))

    folder_path: Mapped[str] = mapped_column(String(1024))
    target_file: Mapped[str] = mapped_column(String(1024))
    program_md: Mapped[str] = mapped_column(Text)

    evaluator_id: Mapped[str] = mapped_column(String(36), ForeignKey("evaluators.id"))

    wall_clock_budget_s: Mapped[int] = mapped_column(Integer, default=600)
    token_cap_session: Mapped[int] = mapped_column(Integer, default=1_000_000)
    token_cap_iter: Mapped[int] = mapped_column(Integer, default=100_000)
    max_files_per_diff: Mapped[int] = mapped_column(Integer, default=1)

    review_mode: Mapped[ReviewMode] = mapped_column(
        Enum(ReviewMode), default=ReviewMode.always
    )
    review_timeout_hours: Mapped[int] = mapped_column(Integer, default=48)
    worktree_prune_window: Mapped[int] = mapped_column(Integer, default=10)
    validation_retry_max: Mapped[int] = mapped_column(Integer, default=3)

    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus), default=SessionStatus.idle, index=True
    )
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)

    session_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    evaluator = relationship("Evaluator")
    experiments = relationship("Experiment", back_populates="session", cascade="all, delete-orphan")
