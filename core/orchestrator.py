"""
AegisFlow Mission Orchestrator
Evidence-gated, self-healing, zero-trust pipeline.

Flow per step:
  1. Guardrail static analysis
  2. Execute in sandbox
  3. Evidence gate (machine-checkable)
  4. On failure → heal → re-run (max attempts)
  5. Never claim success without verified evidence
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Callable, List, Optional

from core.models import (
    ExecutionPlan,
    PlanStep,
    StepAction,
    StepStatus,
    StepRecord,
    MissionReport,
    EvidenceResult,
    new_mission_id,
)
from security.guardrails import analyze_code, analyze_command
from executor.sandbox import run_command, run_python_file, write_file, WORKSPACE
from evidence.gate import verify_step
from agent.healer import heal_step

ROOT = Path(__file__).resolve().parent.parent
AUDIT_DIR = ROOT / "audit_ledger"
CLOUD_DIR = ROOT / "cloud_bridge"
AUDIT_DIR.mkdir(exist_ok=True)
CLOUD_DIR.mkdir(exist_ok=True)

MAX_HEAL_ATTEMPTS = 2


def _log(msg: str, sink: Optional[List[str]] = None):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    if sink is not None:
        sink.append(line)


def execute_step(
    step: PlanStep,
    extra_blocklist: List[str],
    log: List[str],
) -> tuple:
    """
    Guardrail → write/run → return (ExecutionResult|None, GuardrailReport|None, blocked:bool)
    """
    # --- Guardrails ---
    if step.action in (StepAction.CREATE_FILE, StepAction.MODIFY_FILE) and step.content:
        report = analyze_code(step.content, extra_blocklist)
        if not report.safe:
            _log(f"GUARDRAIL BLOCK on {step.id}: {report.block_reasons}", log)
            return None, report, True
        path = write_file(step.file or "script.py", step.content)
        _log(f"WROTE {path}", log)
        # file write itself needs no run
        from core.models import ExecutionResult
        return ExecutionResult(
            command=f"write:{step.file}",
            stdout="",
            stderr="",
            exit_code=0,
            duration=0.0,
        ), report, False

    if step.action == StepAction.RUN_PYTHON:
        # ensure file exists; if content present, write first
        if step.content and step.file:
            gr = analyze_code(step.content, extra_blocklist)
            if not gr.safe:
                _log(f"GUARDRAIL BLOCK on {step.id}: {gr.block_reasons}", log)
                return None, gr, True
            write_file(step.file, step.content)
        target = step.file or "script.py"
        _log(f"RUN_PYTHON {target}", log)
        result = run_python_file(target)
        return result, None, False

    if step.action == StepAction.RUN_COMMAND and step.command:
        gr = analyze_command(step.command, extra_blocklist)
        if not gr.safe:
            _log(f"GUARDRAIL BLOCK on {step.id}: {gr.block_reasons}", log)
            return None, gr, True
        _log(f"RUN_COMMAND {step.command}", log)
        result = run_command(step.command)
        return result, None, False

    from core.models import ExecutionResult
    return ExecutionResult(
        command="noop", stdout="", stderr="No action", exit_code=0, duration=0.0
    ), None, False


def run_mission(
    plan: ExecutionPlan,
    extra_blocklist: Optional[List[str]] = None,
    max_heal: int = MAX_HEAL_ATTEMPTS,
    use_gemini_heal: bool = True,
    event_cb: Optional[Callable[[str, dict], None]] = None,
) -> MissionReport:
    """
    Execute full plan with per-step evidence gating and self-healing.
    event_cb(event_name, payload) optional for live UI updates.
    """
    extra_blocklist = extra_blocklist or []
    log: List[str] = []
    started = datetime.datetime.now().isoformat(timespec="seconds")
    mission_id = new_mission_id()
    records: List[StepRecord] = []
    security_blocks = 0
    heal_count = 0

    def emit(name: str, payload: dict):
        if event_cb:
            event_cb(name, payload)

    _log(f"MISSION {mission_id} START — {plan.objective}", log)
    emit("mission_start", {"id": mission_id, "objective": plan.objective})

    for step in plan.steps:
        record = StepRecord(step=step, status=StepStatus.PENDING)
        emit("step_start", {"id": step.id, "action": step.action.value})

        attempt = 0
        current = step
        verified = False

        while attempt < max_heal + 1 and not verified:
            attempt += 1
            record.status = StepStatus.RUNNING if attempt == 1 else StepStatus.HEALING

            result, guard_report, blocked = execute_step(current, extra_blocklist, log)

            if blocked:
                security_blocks += 1
                record.status = StepStatus.GUARDRAIL_BLOCKED
                record.final_evidence = EvidenceResult(
                    step_id=step.id,
                    attempt=attempt,
                    verified=False,
                    reason="; ".join(guard_report.block_reasons) if guard_report else "Blocked",
                    kind="guardrail",
                )
                record.attempts.append({
                    "attempt": attempt,
                    "blocked": True,
                    "reasons": guard_report.block_reasons if guard_report else [],
                })
                emit("step_blocked", {"id": step.id, "reasons": record.final_evidence.reason})
                break

            evidence = verify_step(step.id, attempt, result, current.evidence)
            record.attempts.append({
                "attempt": attempt,
                "exit_code": result.exit_code,
                "stdout": result.stdout[:500],
                "stderr": result.stderr[:500],
                "duration": result.duration,
                "verified": evidence.verified,
                "reason": evidence.reason,
            })
            emit("step_attempt", {
                "id": step.id,
                "attempt": attempt,
                "verified": evidence.verified,
                "reason": evidence.reason,
            })

            if evidence.verified:
                verified = True
                record.status = StepStatus.VERIFIED
                record.final_evidence = evidence
                _log(f"STEP {step.id} VERIFIED (attempt {attempt}): {evidence.reason}", log)
                break

            # Evidence failed — try heal
            _log(f"STEP {step.id} EVIDENCE FAIL (attempt {attempt}): {evidence.reason}", log)
            if attempt <= max_heal:
                record.status = StepStatus.HEALING
                healed = heal_step(
                    plan.objective, current, result, evidence,
                    use_gemini=use_gemini_heal,
                )
                if healed:
                    heal_count += 1
                    record.healed = True
                    _log(f"HEAL applied for {step.id}", log)
                    # If heal produced new file content, write it; next loop will re-run
                    if healed.content and healed.file:
                        from security.guardrails import analyze_code
                        gr = analyze_code(healed.content, extra_blocklist)
                        if gr.safe:
                            write_file(healed.file, healed.content)
                            # convert to run step for next attempt if needed
                            if current.action == StepAction.RUN_PYTHON:
                                current = PlanStep(
                                    id=current.id,
                                    action=StepAction.RUN_PYTHON,
                                    description=healed.description,
                                    file=healed.file,
                                    content=None,
                                    command=current.command,
                                    evidence=current.evidence,
                                )
                            else:
                                current = healed
                        else:
                            _log(f"Healed code failed guardrails: {gr.block_reasons}", log)
                            record.status = StepStatus.REJECTED
                            record.final_evidence = evidence
                            break
                    else:
                        current = healed
                    emit("step_heal", {"id": step.id, "attempt": attempt})
                else:
                    _log(f"No heal available for {step.id}", log)
                    record.status = StepStatus.REJECTED
                    record.final_evidence = evidence
                    break
            else:
                record.status = StepStatus.REJECTED
                record.final_evidence = evidence

        records.append(record)
        if record.status in (StepStatus.REJECTED, StepStatus.GUARDRAIL_BLOCKED, StepStatus.FAILED):
            # Stop pipeline — do not falsely continue or claim completion
            _log(f"PIPELINE HALTED at {step.id} — status={record.status.value}", log)
            emit("pipeline_halt", {"id": step.id, "status": record.status.value})
            break

    finished = datetime.datetime.now().isoformat(timespec="seconds")
    success = all(r.status == StepStatus.VERIFIED for r in records) and len(records) == len(plan.steps)

    report = MissionReport(
        mission_id=mission_id,
        objective=plan.objective,
        domain=plan.domain,
        started_at=started,
        finished_at=finished,
        success=success,
        steps=records,
        security_blocks=security_blocks,
        heal_count=heal_count,
    )
    report.compute_hash()

    # Persist audit ledger (always local — works offline)
    report_dict = report.to_dict()
    audit_path = AUDIT_DIR / f"{mission_id}.json"
    audit_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")

    # Connectivity-aware sync: if online write cloud_bridge; always enqueue outbox
    try:
        from core.connectivity import is_online, enqueue, save_history_entry, sync_outbox
        online = is_online()
        report_dict["connectivity_at_finish"] = "online" if online else "offline"
        if online:
            cloud_path = CLOUD_DIR / f"{mission_id}.json"
            cloud_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
            enqueue("mission_audit", report_dict, item_id=f"OB-{mission_id}")
            # mark immediately syncable
            sync_outbox()
        else:
            # Critical offline path: queue for later reconciliation
            enqueue("mission_audit", report_dict, item_id=f"OB-{mission_id}")
            _log(f"OFFLINE: mission queued in outbox for sync on reconnect", log)

        save_history_entry({
            "mission_id": mission_id,
            "objective": plan.objective,
            "domain": plan.domain,
            "success": success,
            "hash": report.ledger_hash,
            "started_at": started,
            "finished_at": finished,
            "heal_count": heal_count,
            "security_blocks": security_blocks,
            "connectivity": "online" if online else "offline",
        })
    except Exception as e:
        cloud_path = CLOUD_DIR / f"{mission_id}.json"
        cloud_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
        _log(f"History/outbox note: {e}", log)

    _log(
        f"MISSION {mission_id} END — success={success} hash={report.ledger_hash[:16]}...",
        log,
    )
    emit("mission_end", {
        "id": mission_id,
        "success": success,
        "hash": report.ledger_hash,
    })
    return report
