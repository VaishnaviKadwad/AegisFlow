"""
Controlled execution sandbox.
- Timeout enforcement
- Working directory isolation (workspace/)
- Captures stdout/stderr
- Optional resource-friendly defaults

Note: True isolation requires containers. This provides practical
process-level isolation suitable for hackathon / local demos.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from core.models import ExecutionResult

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"
WORKSPACE.mkdir(exist_ok=True)

DEFAULT_TIMEOUT = 60  # seconds


def run_command(
    command: str,
    timeout: int = DEFAULT_TIMEOUT,
    cwd: str | None = None,
) -> ExecutionResult:
    """Run a shell command with timeout inside workspace by default."""
    start = time.time()
    work = cwd or str(WORKSPACE)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        return ExecutionResult(
            command=command,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            exit_code=result.returncode,
            duration=time.time() - start,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as e:
        return ExecutionResult(
            command=command,
            stdout=(e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
            stderr=f"TIMEOUT after {timeout}s",
            exit_code=-1,
            duration=time.time() - start,
            timed_out=True,
        )
    except Exception as e:
        return ExecutionResult(
            command=command,
            stdout="",
            stderr=str(e),
            exit_code=-1,
            duration=time.time() - start,
            timed_out=False,
        )


def run_python_file(
    filepath: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> ExecutionResult:
    """Execute a Python file under workspace with the current interpreter."""
    path = Path(filepath)
    if not path.is_absolute():
        path = WORKSPACE / path
    cmd = f'python "{path}"'
    return run_command(cmd, timeout=timeout, cwd=str(WORKSPACE))


def write_file(rel_path: str, content: str) -> str:
    """Write content under workspace. Returns absolute path."""
    path = WORKSPACE / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8")
    return str(path)
