import enum


class SessionStatus(str, enum.Enum):
    idle = "idle"
    running = "running"
    paused = "paused"
    draining = "draining"
    stopped = "stopped"
    complete = "complete"


class ReviewMode(str, enum.Enum):
    always = "always"
    improvements_only = "improvements_only"
    auto_approve = "auto_approve"


class ExperimentStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    deciding = "deciding"
    scored = "scored"
    awaiting_review = "awaiting_review"
    kept = "kept"
    reverted = "reverted"
    failed = "failed"
    duplicate = "duplicate"


class Decision(str, enum.Enum):
    approved = "approved"
    rejected = "rejected"
    auto_rejected_timeout = "auto_rejected_timeout"
    auto_rejected_no_improvement = "auto_rejected_no_improvement"


class EvaluatorType(str, enum.Enum):
    command = "command"
    python = "python"
    llm_judge = "llm_judge"


class MetricDirection(str, enum.Enum):
    minimize = "minimize"
    maximize = "maximize"


class NetworkMode(str, enum.Enum):
    none = "none"
    bridge = "bridge"
    egress_proxy = "egress_proxy"  # Phase 2
