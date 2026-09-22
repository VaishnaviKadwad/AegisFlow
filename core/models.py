"""
AegisFlow core data models.
Machine-checkable evidence types support exact match, numeric thresholds,
and structured metric gates (critical for ML verification).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional
import time
import hashlib
import json


class StepAction(str, Enum):
    CREATE_FILE = "create_file"
    MODIFY_FILE = "modify_file"
    RUN_COMMAND = "run_command"
    RUN_PYTHON = "run_python"  # run a python file in sandbox


class EvidenceKind(str, Enum):
    EXACT = "exact"              # stdout must equal expected
    CONTAINS = "contains"        # stdout must contain expected
    NUMERIC_GTE = "numeric_gte"  # parse float from stdout, must be >= threshold
    NUMERIC_LTE = "numeric_lte"
    METRIC_JSON = "metric_json"  # stdout is JSON; check key against threshold
    EXIT_ZERO = "exit_zero"      # only require success exit code
    NONE = "none"                # no output check (file write only)


class StepStatus(str, Enum):
    PENDING = "pending"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    RUNNING = "running"
    FAILED = "failed"
    HEALING = "healing"
    VERIFIED = "verified"
    REJECTED = "rejected"  # ran but evidence failed after max heal attempts


@dataclass
class EvidenceSpec:
    """Machine-checkable evidence required for a step to pass."""
    kind: EvidenceKind = EvidenceKind.EXIT_ZERO
    expected: Optional[str] = None          # for exact / contains
    threshold: Optional[float] = None       # for numeric / metric gates
    metric_key: Optional[str] = None        # for METRIC_JSON e.g. "accuracy"
    tolerance: float = 0.0                  # absolute tolerance for floats


@dataclass
class PlanStep:
    id: str
    action: StepAction
    description: str = ""
    file: Optional[str] = None
    content: Optional[str] = None
    command: Optional[str] = None
    evidence: EvidenceSpec = field(default_factory=EvidenceSpec)


@dataclass
class ExecutionPlan:
    objective: str
    steps: List[PlanStep]
    domain: str = "general"  # "ml", "data", "general"


@dataclass
class ExecutionResult:
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration: float
    timed_out: bool = False


@dataclass
class EvidenceResult:
    step_id: str
    attempt: int
    verified: bool
    reason: str
    kind: str
    actual: str = ""
    expected_summary: str = ""


@dataclass
class StepRecord:
    step: PlanStep
    status: StepStatus
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    final_evidence: Optional[EvidenceResult] = None
    healed: bool = False


@dataclass
class MissionReport:
    mission_id: str
    objective: str
    domain: str
    started_at: str
    finished_at: str
    success: bool
    steps: List[StepRecord]
    ledger_hash: str = ""
    security_blocks: int = 0
    heal_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        def _ser(obj):
            if hasattr(obj, "__dataclass_fields__"):
                return {k: _ser(v) for k, v in asdict(obj).items()}
            if isinstance(obj, Enum):
                return obj.value
            if isinstance(obj, list):
                return [_ser(x) for x in obj]
            if isinstance(obj, dict):
                return {k: _ser(v) for k, v in obj.items()}
            return obj
        return _ser(self)

    def compute_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, default=str)
        self.ledger_hash = hashlib.sha256(payload.encode()).hexdigest()
        return self.ledger_hash


def new_mission_id() -> str:
    return f"AF-{int(time.time())}-{hashlib.sha1(str(time.time()).encode()).hexdigest()[:6]}"
