"""
agent/offline_model.py — Optional local LLM integration (via Ollama) so
AegisFlow can plan and self-heal with real model reasoning while fully
offline — not just the fixed keyword-rule planner in agent/offline_planner.py.

This is entirely optional and additive:
  - If no local model server is running, every function here reports
    "unavailable" and the caller falls back to the deterministic
    rule-based offline planner / offline heal heuristics that already
    exist. Nothing breaks if you never touch this file.

One-time setup on the machine running AegisFlow (no internet needed
afterwards):
    1. Install Ollama: https://ollama.com/download
    2. Pull a small model, e.g.:
         ollama pull llama3.2        # ~2 GB, good quality
         ollama pull qwen2.5:1.5b    # smaller/faster on CPU-only machines
    3. Ollama serves a local HTTP API at http://localhost:11434
       automatically — no server to start by hand.

Only Python's stdlib (urllib) is used here, so no extra pip dependency
is required for this feature to work.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import List, Optional

from agent.prompts import PLANNER_PROMPT, HEALER_PROMPT
from agent.plan_schema import parse_plan_json
from core.models import ExecutionPlan, PlanStep, StepAction, EvidenceSpec, EvidenceKind

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"
_TIMEOUT_PROBE = 1.5
_TIMEOUT_GENERATE = 120


class OfflineModelError(Exception):
    """Raised for expected, user-facing local-model failures."""


def is_available(host: str = DEFAULT_HOST) -> bool:
    """True if a local Ollama server is reachable at `host`."""
    try:
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=_TIMEOUT_PROBE) as resp:
            return resp.status == 200
    except Exception:
        return False


def list_models(host: str = DEFAULT_HOST) -> List[str]:
    """Model names currently pulled/available on the local Ollama server."""
    try:
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=_TIMEOUT_PROBE) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def _ollama_generate(prompt: str, model: str, host: str) -> str:
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json"}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_GENERATE) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise OfflineModelError(
            f"Could not reach local model server at {host}. Is Ollama running? ({e})"
        )
    except Exception as e:
        raise OfflineModelError(f"Local model request failed: {e}")

    text = data.get("response", "")
    if not text:
        raise OfflineModelError(
            f"Local model '{model}' returned an empty response. "
            f"Is it pulled? Try: ollama pull {model}"
        )
    return text


def create_plan_offline_model(
    user_task: str,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
) -> ExecutionPlan:
    """
    Generate a structured, evidence-gated ExecutionPlan using a local LLM
    (via Ollama) — fully offline, no Gemini / internet required.
    Raises OfflineModelError on any failure; caller should fall back to
    agent.offline_planner.plan_offline().
    """
    if not is_available(host):
        raise OfflineModelError(
            f"No local model server detected at {host}. "
            f"Install Ollama and run `ollama pull {model}` first."
        )

    prompt = f"""{PLANNER_PROMPT}

USER OBJECTIVE:
{user_task}

Respond with ONLY a single valid JSON object (no markdown fences, no commentary).
It MUST include:
- "objective": string (copy the user objective)
- "domain": "ml" or "general" or "data"
- "steps": array of step objects, each with id, action, description, and evidence.
"""
    text = _ollama_generate(prompt, model, host)
    try:
        return parse_plan_json(text, user_task)
    except Exception as e:
        raise OfflineModelError(f"Local model produced an unusable plan: {e}")


def heal_step_offline_model(
    step: PlanStep,
    error_text: str,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
) -> Optional[PlanStep]:
    """
    Ask the local model to propose a corrected replacement for a failed step.
    Returns None on any failure so the caller can fall back to offline
    heuristics — never raises.
    """
    if not is_available(host):
        return None

    prompt = f"""{HEALER_PROMPT}

FAILED STEP (id={step.id}):
action: {step.action.value}
file: {step.file}
command: {step.command}
content:
{step.content or "(none)"}

ERROR / EVIDENCE FAILURE:
{error_text[:2000]}

Respond with ONLY a single valid JSON object describing the corrected step, e.g.:
{{"id": "{step.id}", "action": "run_python", "file": "workspace/train.py",
  "content": "...", "command": null,
  "evidence": {{"kind": "metric_json", "metric_key": "accuracy", "threshold": 0.9}}}}
"""
    try:
        text = _ollama_generate(prompt, model, host)
        raw = json.loads(text)
    except Exception:
        return None

    try:
        action = StepAction(raw.get("action", step.action.value))
    except ValueError:
        action = step.action

    ev_raw = raw.get("evidence") or {}
    try:
        kind = EvidenceKind(ev_raw.get("kind", step.evidence.kind.value))
    except ValueError:
        kind = step.evidence.kind

    return PlanStep(
        id=raw.get("id", step.id),
        action=action,
        description=raw.get("description", step.description),
        file=raw.get("file", step.file),
        content=raw.get("content", step.content),
        command=raw.get("command", step.command),
        evidence=EvidenceSpec(
            kind=kind,
            expected=ev_raw.get("expected"),
            threshold=ev_raw.get("threshold"),
            metric_key=ev_raw.get("metric_key"),
            tolerance=ev_raw.get("tolerance", 0.0) or 0.0,
        ),
    )
