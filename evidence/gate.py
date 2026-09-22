"""
Zero-Trust Evidence Gate.
Machine-checkable verification — never claims success without evidence.
Supports exact, contains, numeric thresholds, and JSON metric gates (ML-ready).
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from core.models import EvidenceKind, EvidenceSpec, EvidenceResult, ExecutionResult


def _first_float(text: str) -> Optional[float]:
    """Extract first floating-point number from text."""
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text.replace(",", ""))
    if m:
        try:
            return float(m.group())
        except ValueError:
            return None
    return None


def _parse_metric_json(stdout: str, key: str) -> Optional[float]:
    """Parse stdout as JSON (or last JSON object) and pull metric key."""
    text = stdout.strip()
    candidates = [text]
    # try last {...} block
    start = text.rfind("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for c in candidates:
        try:
            data = json.loads(c)
            if isinstance(data, dict) and key in data:
                return float(data[key])
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return None


def verify_step(
    step_id: str,
    attempt: int,
    result: ExecutionResult,
    spec: EvidenceSpec,
) -> EvidenceResult:
    """
    Verify one execution attempt against machine-checkable evidence.
    Returns EvidenceResult — verified=True only when evidence holds.
    """
    kind = spec.kind if isinstance(spec.kind, EvidenceKind) else EvidenceKind(spec.kind)
    actual = (result.stdout or "").strip()
    expected_summary = ""

    # Hard fail on non-zero exit (except pure NONE with no run)
    if result.timed_out:
        return EvidenceResult(
            step_id=step_id, attempt=attempt, verified=False,
            reason="Execution timed out.", kind=kind.value, actual=actual,
        )

    if result.exit_code != 0 and kind != EvidenceKind.NONE:
        err = (result.stderr or result.stdout or "").strip()[:400]
        return EvidenceResult(
            step_id=step_id, attempt=attempt, verified=False,
            reason=f"Non-zero exit code {result.exit_code}. stderr: {err}",
            kind=kind.value, actual=actual,
        )

    if kind == EvidenceKind.NONE or kind == EvidenceKind.EXIT_ZERO:
        return EvidenceResult(
            step_id=step_id, attempt=attempt, verified=True,
            reason="Exit code 0 — step accepted.", kind=kind.value, actual=actual,
        )

    if kind == EvidenceKind.EXACT:
        expected_summary = str(spec.expected)
        ok = actual == str(spec.expected).strip()
        return EvidenceResult(
            step_id=step_id, attempt=attempt, verified=ok,
            reason="Exact match." if ok else f"Expected exactly '{spec.expected}', got '{actual[:200]}'.",
            kind=kind.value, actual=actual, expected_summary=expected_summary,
        )

    if kind == EvidenceKind.CONTAINS:
        expected_summary = str(spec.expected)
        ok = str(spec.expected) in actual
        return EvidenceResult(
            step_id=step_id, attempt=attempt, verified=ok,
            reason="Substring found." if ok else f"Expected stdout to contain '{spec.expected}'.",
            kind=kind.value, actual=actual, expected_summary=expected_summary,
        )

    if kind == EvidenceKind.NUMERIC_GTE:
        val = _first_float(actual)
        thr = float(spec.threshold) if spec.threshold is not None else 0.0
        expected_summary = f">= {thr}"
        if val is None:
            return EvidenceResult(
                step_id=step_id, attempt=attempt, verified=False,
                reason="Could not parse numeric value from stdout.",
                kind=kind.value, actual=actual, expected_summary=expected_summary,
            )
        ok = val + (spec.tolerance or 0) >= thr
        return EvidenceResult(
            step_id=step_id, attempt=attempt, verified=ok,
            reason=f"Value {val} {'meets' if ok else 'fails'} threshold >= {thr}.",
            kind=kind.value, actual=str(val), expected_summary=expected_summary,
        )

    if kind == EvidenceKind.NUMERIC_LTE:
        val = _first_float(actual)
        thr = float(spec.threshold) if spec.threshold is not None else 0.0
        expected_summary = f"<= {thr}"
        if val is None:
            return EvidenceResult(
                step_id=step_id, attempt=attempt, verified=False,
                reason="Could not parse numeric value from stdout.",
                kind=kind.value, actual=actual, expected_summary=expected_summary,
            )
        ok = val - (spec.tolerance or 0) <= thr
        return EvidenceResult(
            step_id=step_id, attempt=attempt, verified=ok,
            reason=f"Value {val} {'meets' if ok else 'fails'} threshold <= {thr}.",
            kind=kind.value, actual=str(val), expected_summary=expected_summary,
        )

    if kind == EvidenceKind.METRIC_JSON:
        key = spec.metric_key or "accuracy"
        thr = float(spec.threshold) if spec.threshold is not None else 0.0
        expected_summary = f"{key} >= {thr}"
        val = _parse_metric_json(actual, key)
        if val is None:
            return EvidenceResult(
                step_id=step_id, attempt=attempt, verified=False,
                reason=f"Could not find metric '{key}' in JSON stdout.",
                kind=kind.value, actual=actual[:300], expected_summary=expected_summary,
            )
        ok = val + (spec.tolerance or 0) >= thr
        return EvidenceResult(
            step_id=step_id, attempt=attempt, verified=ok,
            reason=f"Metric {key}={val} {'meets' if ok else 'fails'} threshold >= {thr}.",
            kind=kind.value, actual=str(val), expected_summary=expected_summary,
        )

    return EvidenceResult(
        step_id=step_id, attempt=attempt, verified=False,
        reason=f"Unknown evidence kind: {kind}", kind=str(kind), actual=actual,
    )
