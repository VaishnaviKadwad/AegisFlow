"""
agent/plan_schema.py — Shared Pydantic schema + JSON parsing for turning an
LLM's raw text output (Gemini or a local model) into a validated
ExecutionPlan.

Both agent/planner.py (Gemini) and agent/offline_model.py (local/offline
LLM via Ollama) import from here so the two planners produce identically
-shaped, identically-validated plans.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from pydantic import BaseModel, Field

from core.models import (
    ExecutionPlan,
    PlanStep,
    StepAction,
    EvidenceSpec,
    EvidenceKind,
)


class EvidenceSchema(BaseModel):
    kind: str = Field(default="exit_zero")
    expected: Optional[str] = None
    threshold: Optional[float] = None
    metric_key: Optional[str] = None
    tolerance: float = 0.0


class PlanStepSchema(BaseModel):
    id: str = "S1"
    action: str = "run_command"
    description: str = ""
    file: Optional[str] = None
    content: Optional[str] = None
    command: Optional[str] = None
    evidence: EvidenceSchema = Field(default_factory=EvidenceSchema)


class ExecutionPlanSchema(BaseModel):
    objective: str = ""
    domain: str = "general"
    steps: List[PlanStepSchema] = Field(default_factory=list)


def to_plan(schema: ExecutionPlanSchema, fallback_objective: str = "") -> ExecutionPlan:
    steps: List[PlanStep] = []
    for s in schema.steps:
        try:
            action = StepAction(s.action)
        except ValueError:
            action = StepAction.RUN_COMMAND
        try:
            kind = EvidenceKind(s.evidence.kind if s.evidence else "exit_zero")
        except ValueError:
            kind = EvidenceKind.EXIT_ZERO
        ev = s.evidence or EvidenceSchema()
        steps.append(PlanStep(
            id=s.id or "S1",
            action=action,
            description=s.description or "",
            file=s.file,
            content=s.content,
            command=s.command,
            evidence=EvidenceSpec(
                kind=kind,
                expected=ev.expected,
                threshold=ev.threshold,
                metric_key=ev.metric_key,
                tolerance=ev.tolerance or 0.0,
            ),
        ))
    obj = (schema.objective or "").strip() or fallback_objective
    return ExecutionPlan(objective=obj, steps=steps, domain=schema.domain or "general")


def parse_plan_json(text: str, user_task: str) -> ExecutionPlan:
    """Parse JSON text (from any LLM) into ExecutionPlan, filling missing fields."""
    text = (text or "").strip()
    # strip markdown fences some models add despite instructions
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise RuntimeError(f"Planner returned non-JSON: {text[:400]}")
    raw = json.loads(m.group())

    # Fill missing top-level fields
    if not raw.get("objective"):
        raw["objective"] = user_task
    if "domain" not in raw:
        raw["domain"] = "ml" if any(
            w in user_task.lower() for w in ("train", "model", "accuracy", "sklearn", "iris", "ml")
        ) else "general"
    if "steps" not in raw or not isinstance(raw["steps"], list):
        raw["steps"] = []

    # Normalize each step
    for i, step in enumerate(raw["steps"]):
        if not isinstance(step, dict):
            continue
        step.setdefault("id", f"S{i+1}")
        step.setdefault("action", "run_command")
        step.setdefault("description", "")
        if "evidence" not in step or not isinstance(step.get("evidence"), dict):
            step["evidence"] = {"kind": "exit_zero"}
        else:
            step["evidence"].setdefault("kind", "exit_zero")

    schema = ExecutionPlanSchema.model_validate(raw)
    if not schema.steps:
        raise RuntimeError("Planner returned a plan with zero steps.")
    return to_plan(schema, fallback_objective=user_task)
