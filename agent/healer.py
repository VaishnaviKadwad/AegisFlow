"""
Self-healing loop: feed failure evidence + traceback to Gemini (or offline fix)
and produce a corrected step. Never claims success — only proposes a patch.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from agent.prompts import HEALER_PROMPT
from core.models import PlanStep, StepAction, EvidenceSpec, EvidenceKind, EvidenceResult, ExecutionResult

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"


def _read_workspace_file(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    path = WORKSPACE / filename
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


def _offline_heal(step: PlanStep, error_text: str) -> Optional[PlanStep]:
    """
    Deterministic offline heals — no internet required.
    Handles the intentional X_trian typo and common NameError patterns.
    """
    content = step.content or _read_workspace_file(step.file)
    if not content:
        return None

    fixed = content
    changed = False

    # 1) Classic demo typo
    if "X_trian" in fixed:
        fixed = fixed.replace("X_trian", "X_train")
        changed = True

    # 2) NameError: name 'Foo' is not defined — try common ML typos
    m = re.search(r"NameError: name '(\w+)' is not defined", error_text)
    if m:
        bad = m.group(1)
        # common corrections
        corrections = {
            "X_trian": "X_train",
            "y_trian": "y_train",
            "X_tst": "X_test",
            "y_tst": "y_test",
            "accuarcy": "accuracy",
            "LogisticRegresion": "LogisticRegression",
        }
        if bad in corrections and bad in fixed:
            fixed = fixed.replace(bad, corrections[bad])
            changed = True
        # Did you mean: 'X_train'?
        m2 = re.search(r"Did you mean: '(\w+)'\?", error_text)
        if m2 and bad in fixed:
            fixed = fixed.replace(bad, m2.group(1))
            changed = True

    # 3) ModuleNotFoundError for common sklearn import typos
    if "No module named" in error_text and "sklearn.linear" in error_text:
        fixed = fixed.replace(
            "from sklearn.linear import LogisticRegression",
            "from sklearn.linear_model import LogisticRegression",
        )
        changed = True

    if not changed:
        return None

    return PlanStep(
        id=step.id,
        action=StepAction.CREATE_FILE,  # rewrite file, then orchestrator re-runs
        description=(step.description or "") + " [healed offline]",
        file=step.file or "healed_script.py",
        content=fixed,
        command=step.command,
        evidence=step.evidence,
    )


def heal_step(
    objective: str,
    step: PlanStep,
    exec_result: ExecutionResult,
    evidence: EvidenceResult,
    model: str = "gemini-2.5-flash",
    use_gemini: bool = True,
) -> Optional[PlanStep]:
    """
    Attempt to produce a corrected PlanStep.
    Always tries offline heuristics first (works without internet).
    Optionally upgrades with Gemini when available.
    """
    error_blob = (
        f"stderr:\n{exec_result.stderr}\n"
        f"stdout:\n{exec_result.stdout}\n"
        f"exit_code: {exec_result.exit_code}\n"
        f"evidence: {evidence.reason}\n"
    )

    offline = _offline_heal(step, error_blob)

    # Offline-only mode
    if not use_gemini or not os.getenv("GEMINI_API_KEY"):
        return offline

    # Live Gemini mode (for evaluation): try Gemini first, offline as backup

    try:
        from google import genai
        from google.genai import types
        from pydantic import BaseModel, Field
        from typing import Optional as Opt

        class HealSchema(BaseModel):
            id: str = "S1"
            action: str = "create_file"
            description: str = ""
            file: Opt[str] = None
            content: Opt[str] = None
            command: Opt[str] = None
            evidence_kind: str = "exit_zero"
            evidence_expected: Opt[str] = None
            evidence_threshold: Opt[float] = None
            evidence_metric_key: Opt[str] = None

        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        original = step.content or _read_workspace_file(step.file) or ""
        prompt = f"""{HEALER_PROMPT}

OBJECTIVE: {objective}
FAILED STEP ID: {step.id}
FAILED ACTION: {step.action.value}
FILE: {step.file}
COMMAND: {step.command}
ORIGINAL CODE:
```
{original}
```

FAILURE DETAILS:
{error_blob}

Return a corrected step as JSON with fields: id, action, description, file, content, command,
evidence_kind, evidence_expected, evidence_threshold, evidence_metric_key.
Prefer action=create_file with fixed full file content.
"""
        models = [model, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-8b"]
        data = None
        last_err = None
        for mid in models:
            try:
                response = client.models.generate_content(
                    model=mid,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=HealSchema,
                    ),
                )
                data = HealSchema.model_validate_json(response.text)
                break
            except Exception as e:
                last_err = e
                try:
                    response = client.models.generate_content(model=mid, contents=prompt)
                    import json as _json
                    t = response.text or ""
                    m = re.search(r"\{[\s\S]*\}", t)
                    if m:
                        raw = _json.loads(m.group())
                        raw.setdefault("id", step.id)
                        raw.setdefault("action", "create_file")
                        data = HealSchema.model_validate(raw)
                        break
                except Exception as e2:
                    last_err = e2
                    continue
        if data is None:
            print(f"[AegisFlow] Gemini heal failed, offline fallback: {last_err}")
            return offline

        try:
            action = StepAction(data.action)
        except ValueError:
            action = StepAction.CREATE_FILE
        try:
            kind = EvidenceKind(data.evidence_kind)
        except ValueError:
            kind = step.evidence.kind

        return PlanStep(
            id=data.id or step.id,
            action=action,
            description=(data.description or step.description) + " [healed]",
            file=data.file or step.file,
            content=data.content or step.content,
            command=data.command or step.command,
            evidence=EvidenceSpec(
                kind=kind,
                expected=data.evidence_expected or step.evidence.expected,
                threshold=data.evidence_threshold if data.evidence_threshold is not None else step.evidence.threshold,
                metric_key=data.evidence_metric_key or step.evidence.metric_key,
            ),
        )
    except Exception as e:
        print(f"[AegisFlow] Gemini heal exception, offline fallback: {e}")
        return offline
