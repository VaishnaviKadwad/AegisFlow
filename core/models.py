# core/models.py
from dataclasses import dataclass

@dataclass
class ExecutionResult:
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration: float

@dataclass
class Evidence:
    step_id: str
    attempt: int
    verified: bool
    reason: str
    stdout: str
    stderr: str
    exit_code: int