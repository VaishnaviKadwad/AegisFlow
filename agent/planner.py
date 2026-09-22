"""
Gemini-backed structured planner with Pydantic schema validation.
Produces machine-checkable plans including evidence specs for ML gates.
Robust to incomplete Gemini responses.
"""

from __future__ import annotations

import json
import os
import re
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from agent.prompts import PLANNER_PROMPT
from core.models import (
    ExecutionPlan,
    PlanStep,
    StepAction,
    EvidenceSpec,
    EvidenceKind,
)

load_dotenv()


# ---- Pydantic schemas for Gemini structured output ----

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


def _get_client():
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. "
            "Create a .env file with GEMINI_API_KEY=your_key or set the environment variable."
        )
    return genai.Client(api_key=api_key)


def _to_plan(schema: ExecutionPlanSchema, fallback_objective: str = "") -> ExecutionPlan:
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


def _parse_plan_json(text: str, user_task: str) -> ExecutionPlan:
    """Parse JSON text into ExecutionPlan, filling missing fields."""
    text = (text or "").strip()
    # strip markdown fences
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
    return _to_plan(schema, fallback_objective=user_task)


# Models to try in order (newer first)
_MODEL_CANDIDATES = [
    "gemini-2.5-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash-8b",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
]


def create_plan(user_task: str, model: str | None = None) -> ExecutionPlan:
    """Call Gemini to produce a validated ExecutionPlan. Robust to schema gaps."""
    from google.genai import types

    client = _get_client()
    prompt = f"""{PLANNER_PROMPT}

USER OBJECTIVE:
{user_task}

IMPORTANT: Your JSON MUST include all of these top-level fields:
- "objective": string (copy the user objective)
- "domain": "ml" or "general" or "data"
- "steps": array of step objects

Each step MUST have: id, action, and evidence with at least "kind".
"""

    models = [model] if model else _MODEL_CANDIDATES
    last_err: Exception | None = None

    for mid in models:
        try:
            # Attempt 1: structured schema
            try:
                response = client.models.generate_content(
                    model=mid,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ExecutionPlanSchema,
                    ),
                )
                text = response.text or ""
                plan = _parse_plan_json(text, user_task)
                print(f"[AegisFlow] Gemini plan OK via model={mid} steps={len(plan.steps)}")
                return plan
            except Exception as e1:
                last_err = e1
                # Attempt 2: free JSON
                response = client.models.generate_content(
                    model=mid,
                    contents=prompt + "\n\nRespond with ONLY valid JSON. No markdown.",
                )
                text = response.text or ""
                return _parse_plan_json(text, user_task)
        except Exception as e:
            last_err = e
            continue

    # Graceful degradation: use offline planner instead of crashing the mission
    try:
        from agent.offline_planner import plan_offline
        print(f"[AegisFlow] Gemini unavailable ({last_err}). Falling back to offline planner.")
        return plan_offline(user_task)
    except Exception as e2:
        raise RuntimeError(
            f"All Gemini models failed and offline fallback failed.\n"
            f"Gemini error: {last_err}\nOffline error: {e2}\n"
            f"Tried: {models}"
        )


# ---- Deterministic offline plans for demos (no API key required) ----

def offline_plan_fibonacci() -> ExecutionPlan:
    code = '''def fibonacci(n):
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b

if __name__ == "__main__":
    print(fibonacci(30))
'''
    return ExecutionPlan(
        objective="Create Fibonacci and verify fib(30)=832040",
        domain="general",
        steps=[
            PlanStep(
                id="S1",
                action=StepAction.CREATE_FILE,
                description="Write fibonacci.py",
                file="fibonacci.py",
                content=code,
                evidence=EvidenceSpec(kind=EvidenceKind.NONE),
            ),
            PlanStep(
                id="S2",
                action=StepAction.RUN_PYTHON,
                description="Run fibonacci.py and verify output",
                file="fibonacci.py",
                command="python fibonacci.py",
                evidence=EvidenceSpec(kind=EvidenceKind.EXACT, expected="832040"),
            ),
        ],
    )


def offline_plan_ml_iris() -> ExecutionPlan:
    """Train logistic regression on Iris; evidence gate on accuracy >= 0.90."""
    code = '''import json
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score

X, y = load_iris(return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=y
)
clf = LogisticRegression(max_iter=500)
clf.fit(X_train, y_train)
pred = clf.predict(X_test)
metrics = {
    "accuracy": float(accuracy_score(y_test, pred)),
    "f1": float(f1_score(y_test, pred, average="macro")),
    "n_test": int(len(y_test)),
}
print(json.dumps(metrics))
'''
    return ExecutionPlan(
        objective="Train Iris classifier and verify accuracy >= 0.90",
        domain="ml",
        steps=[
            PlanStep(
                id="S1",
                action=StepAction.CREATE_FILE,
                description="Write Iris training script",
                file="train_iris.py",
                content=code,
                evidence=EvidenceSpec(kind=EvidenceKind.NONE),
            ),
            PlanStep(
                id="S2",
                action=StepAction.RUN_PYTHON,
                description="Train model and emit metrics JSON",
                file="train_iris.py",
                command="python train_iris.py",
                evidence=EvidenceSpec(
                    kind=EvidenceKind.METRIC_JSON,
                    metric_key="accuracy",
                    threshold=0.90,
                ),
            ),
        ],
    )


def offline_plan_ml_buggy() -> ExecutionPlan:
    """Intentionally buggy ML script to demonstrate self-healing."""
    buggy = '''import json
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

X, y = load_iris(return_X_y=True)
# BUG: undefined variable X_trian (typo)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=0)
clf = LogisticRegression(max_iter=300)
clf.fit(X_trian, y_train)  # NameError on purpose
pred = clf.predict(X_test)
print(json.dumps({"accuracy": float(accuracy_score(y_test, pred))}))
'''
    return ExecutionPlan(
        objective="Train Iris model (buggy) — self-heal expected",
        domain="ml",
        steps=[
            PlanStep(
                id="S1",
                action=StepAction.CREATE_FILE,
                description="Write buggy training script",
                file="train_buggy.py",
                content=buggy,
                evidence=EvidenceSpec(kind=EvidenceKind.NONE),
            ),
            PlanStep(
                id="S2",
                action=StepAction.RUN_PYTHON,
                description="Run buggy script (will fail then heal)",
                file="train_buggy.py",
                command="python train_buggy.py",
                evidence=EvidenceSpec(
                    kind=EvidenceKind.METRIC_JSON,
                    metric_key="accuracy",
                    threshold=0.85,
                ),
            ),
        ],
    )
