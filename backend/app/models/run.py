import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    experiment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiments.id"), index=True
    )

    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    stdout_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    stderr_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    metric_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    experiment = relationship("Experiment", back_populates="runs")
