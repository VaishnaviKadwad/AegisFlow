"""
Intermittent connectivity support for AegisFlow.

Critical offline functions (no internet required):
  - Offline mission planning (deterministic plans)
  - Guardrails (AST)
  - Sandbox execution
  - Evidence gates
  - Local audit ledger writes
  - Offline self-heal heuristics

When online is restored:
  - Flush outbox queue to cloud_bridge/
  - Mark missions as synced
  - Optional: note that Gemini is available again
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
OUTBOX_DIR = ROOT / "outbox"
OUTBOX_DIR.mkdir(exist_ok=True)
HISTORY_INDEX = ROOT / "audit_ledger" / "history_index.json"
HISTORY_INDEX.parent.mkdir(exist_ok=True)
CLOUD_DIR = ROOT / "cloud_bridge"
CLOUD_DIR.mkdir(exist_ok=True)
AUDIT_DIR = ROOT / "audit_ledger"
AUDIT_DIR.mkdir(exist_ok=True)

# How we probe connectivity (short timeout)
_PROBE_HOSTS = [
    ("8.8.8.8", 53),
    ("1.1.1.1", 53),
]
_HTTP_PROBE = "https://www.google.com/generate_204"


def is_online(timeout: float = 1.5) -> bool:
    """Return True if network appears available."""
    for host, port in _PROBE_HOSTS:
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return True
        except OSError:
            pass
    try:
        urllib.request.urlopen(_HTTP_PROBE, timeout=timeout)
        return True
    except Exception:
        return False


@dataclass
class OutboxItem:
    id: str
    created_at: str
    kind: str  # "mission_audit" | "event"
    payload: Dict[str, Any]
    synced: bool = False
    synced_at: Optional[str] = None


def _outbox_path(item_id: str) -> Path:
    return OUTBOX_DIR / f"{item_id}.json"


def enqueue(kind: str, payload: Dict[str, Any], item_id: Optional[str] = None) -> OutboxItem:
    """Queue data generated during outage (or always, for reliable sync)."""
    oid = item_id or f"OB-{int(time.time())}-{os.urandom(3).hex()}"
    item = OutboxItem(
        id=oid,
        created_at=datetime.now().isoformat(timespec="seconds"),
        kind=kind,
        payload=payload,
        synced=False,
    )
    _outbox_path(oid).write_text(json.dumps(asdict(item), indent=2), encoding="utf-8")
    return item


def list_outbox(include_synced: bool = False) -> List[OutboxItem]:
    items: List[OutboxItem] = []
    for p in sorted(OUTBOX_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            item = OutboxItem(**data)
            if include_synced or not item.synced:
                items.append(item)
        except Exception:
            continue
    return items


def pending_count() -> int:
    return len(list_outbox(include_synced=False))


def sync_outbox() -> Dict[str, Any]:
    """
    Reconcile outbox when connectivity is back.
    Copies mission audits into cloud_bridge/ and marks items synced.
    Returns summary for UI.
    """
    pending = list_outbox(include_synced=False)
    synced_ids: List[str] = []
    errors: List[str] = []

    for item in pending:
        try:
            if item.kind == "mission_audit":
                mid = item.payload.get("mission_id") or item.id
                dest = CLOUD_DIR / f"{mid}_synced.json"
                dest.write_text(json.dumps(item.payload, indent=2), encoding="utf-8")
                # also ensure audit_ledger has it
                audit_dest = AUDIT_DIR / f"{mid}.json"
                if not audit_dest.exists():
                    audit_dest.write_text(json.dumps(item.payload, indent=2), encoding="utf-8")
            else:
                dest = CLOUD_DIR / f"event_{item.id}.json"
                dest.write_text(json.dumps(item.payload, indent=2), encoding="utf-8")

            item.synced = True
            item.synced_at = datetime.now().isoformat(timespec="seconds")
            _outbox_path(item.id).write_text(json.dumps(asdict(item), indent=2), encoding="utf-8")
            synced_ids.append(item.id)
        except Exception as e:
            errors.append(f"{item.id}: {e}")

    return {
        "synced_count": len(synced_ids),
        "synced_ids": synced_ids,
        "errors": errors,
        "remaining": pending_count(),
        "synced_at": datetime.now().isoformat(timespec="seconds"),
    }


# ───── Mission history index ─────

def load_history() -> List[Dict[str, Any]]:
    if not HISTORY_INDEX.exists():
        return []
    try:
        return json.loads(HISTORY_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_history_entry(entry: Dict[str, Any]) -> None:
    history = load_history()
    # de-dupe by mission_id
    history = [h for h in history if h.get("mission_id") != entry.get("mission_id")]
    history.append(entry)
    # keep last 100
    history = history[-100:]
    HISTORY_INDEX.write_text(json.dumps(history, indent=2), encoding="utf-8")


def load_mission_report(mission_id: str) -> Optional[Dict[str, Any]]:
    path = AUDIT_DIR / f"{mission_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    # try outbox
    for item in list_outbox(include_synced=True):
        if item.payload.get("mission_id") == mission_id:
            return item.payload
    return None


def connectivity_status() -> Dict[str, Any]:
    online = is_online()
    return {
        "online": online,
        "mode": "ONLINE" if online else "OFFLINE",
        "pending_outbox": pending_count(),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "critical_offline_functions": [
            "Offline planning (Fibonacci / ML Iris / buggy heal demos)",
            "AST security guardrails",
            "Sandbox code execution",
            "Evidence gates (exact / metric JSON)",
            "Local audit ledger + outbox queue",
            "Offline self-heal heuristics",
        ],
    }
