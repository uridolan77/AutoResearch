import uuid

from sqlalchemy import JSON, Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import EvaluatorType, MetricDirection, NetworkMode


def _uuid() -> str:
    return str(uuid.uuid4())


class Evaluator(Base):
    __tablename__ = "evaluators"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True)

    type: Mapped[EvaluatorType] = mapped_column(Enum(EvaluatorType))
    config: Mapped[dict] = mapped_column(JSON)

    metric_name: Mapped[str] = mapped_column(String(255))
    direction: Mapped[MetricDirection] = mapped_column(Enum(MetricDirection))

    timeout_s: Mapped[int] = mapped_column(Integer, default=600)
    baseline_required: Mapped[bool] = mapped_column(Boolean, default=True)

    network_mode: Mapped[NetworkMode] = mapped_column(
        Enum(NetworkMode), default=NetworkMode.none
    )
    network_allow: Mapped[list | None] = mapped_column(JSON, nullable=True)
    secret_refs: Mapped[list | None] = mapped_column(JSON, nullable=True)
