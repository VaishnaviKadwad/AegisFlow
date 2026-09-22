"""
Offline LLM via Ollama (runs fully on your machine — no internet).

Install once:
  1. https://ollama.com  → install
  2. ollama pull llama3.2
  3. ollama serve   (usually auto-starts)

.env (optional):
  OLLAMA_HOST=http://localhost:11434
  OLLAMA_MODEL=llama3.2
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")


def is_ollama_available(timeout: float = 1.5) -> bool:
    """True if Ollama is reachable locally."""
    try:
        req = urllib.request.Request(f"{DEFAULT_HOST}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def ollama_generate(prompt: str, model: Optional[str] = None, timeout: float = 120) -> str:
    """Call local Ollama /api/generate and return response text."""
    model = model or DEFAULT_MODEL
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{DEFAULT_HOST}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return (data.get("response") or "").strip()
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Ollama not reachable at {DEFAULT_HOST}. "
            f"Install from https://ollama.com and run: ollama pull {model}\n"
            f"Detail: {e}"
        ) from e


def create_plan_ollama(user_task: str, model: Optional[str] = None):
    """
    Use local Ollama model to produce an ExecutionPlan (same schema as Gemini).
    """
    from agent.prompts import PLANNER_PROMPT
    from agent.planner import _parse_plan_json

    prompt = f"""{PLANNER_PROMPT}

USER OBJECTIVE:
{user_task}

Respond with ONLY valid JSON (no markdown). Required fields:
- "objective": string
- "domain": "ml" | "general" | "data"
- "steps": array of objects with id, action, evidence.kind
Allowed actions: create_file, modify_file, run_command, run_python
"""
    text = ollama_generate(prompt, model=model)
    return _parse_plan_json(text, user_task)


def heal_with_ollama(
    objective: str,
    step_id: str,
    step_action: str,
    file: str,
    content: str,
    error_text: str,
    model: Optional[str] = None,
) -> Optional[dict]:
    """Ask local model to fix a failed step. Returns dict with content/file or None."""
    prompt = f"""You are a code-fix assistant for AegisFlow.
A step failed. Return ONLY valid JSON for a corrected step:
{{"id": "{step_id}", "action": "{step_action}", "file": "{file or "script.py"}", "content": "...fixed python code...", "description": "fixed"}}

Objective: {objective}
Error:
{error_text[:1500]}

Broken code:
{content[:2000] if content else "(no content)"}

Rules: fix the bug, print required metrics as JSON if ML, never use os.system/eval/exec.
"""
    try:
        text = ollama_generate(prompt, model=model)
        # extract JSON
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0:
            return None
        return json.loads(text[start : end + 1])
    except Exception:
        return None
