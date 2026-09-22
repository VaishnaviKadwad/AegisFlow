# 🛡️ AegisFlow

**Evidence-Gated Self-Healing Agent Workflow**

Zero-trust AI agent that executes multi-step tasks, verifies every action with **machine-checkable evidence**, detects failures, and safely recovers or re-plans — **without ever falsely claiming completion**.

Built for Hackdays @ MSRIT · Problem statement **A1**.

---

## Problem it solves

Autonomous agents often:

1. Run unsafe AI-generated code
2. Crash and stop
3. Or worse — report success when the output is wrong

AegisFlow enforces a strict pipeline:

```
Objective → Plan → Guardrails → Sandbox Execute → Evidence Gate
                         ↑                            │
                         └── Self-Heal (re-plan) ←────┘ fail
                                      │
                                   VERIFIED → Cryptographic Audit Ledger
```

Success is **only** declared when every step passes a machine-checkable evidence gate.

---

## Core features

| Layer | What it does |
|-------|----------------|
| **AI Planner** | Gemini (or offline demos) → structured multi-step plan with evidence specs |
| **Dynamic Guardrails** | AST static analysis blocks `eval`, `exec`, `os.system`, `subprocess`, etc. |
| **Isolated Sandbox** | Timed subprocess execution inside `workspace/` |
| **Evidence Gate** | Exact / contains / numeric threshold / **JSON metric** (ML-ready) |
| **Self-Healing Loop** | On failure: traceback → heal → rewrite → re-run (max N attempts) |
| **Audit Ledger** | SHA-256 of full mission report → `audit_ledger/` + `cloud_bridge/` |
| **Cyberpunk HUD** | Streamlit dashboard with live plan, evidence trail, heal badges, hash |

---

## ML-ready evidence

For model training missions, scripts **must** print metrics as JSON:

```json
{"accuracy": 0.96, "f1": 0.94}
```

Evidence spec example:

```text
kind: metric_json
metric_key: accuracy
threshold: 0.90
```

Gate passes only if `accuracy >= 0.90`. Wrong metrics → reject → heal → retry. **No silent success.**

---

## Quick start

```bash
cd AegisFlow
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Optional: live Gemini planning / healing
export GEMINI_API_KEY=your_key_here

# Launch dashboard
streamlit run ui/app.py
```

### Demo scenarios (no API key required)

| Scenario | What you see |
|----------|----------------|
| **A · Fibonacci** | Exact evidence gate (`832040`) |
| **B · ML Iris** | Train logistic regression → JSON metric gate `accuracy ≥ 0.90` |
| **C · Buggy ML + Self-Heal** | Intentional `NameError` → auto-heal typo → re-run → verified |
| **D · Guardrail Block** | `os.system` payload blocked before execution |

---

## Project layout

```
AegisFlow/
├── agent/           # Planner + Healer + prompts
├── core/            # Models + Orchestrator
├── evidence/        # Machine-checkable evidence gate
├── executor/        # Sandbox runner
├── security/        # AST guardrails
├── ui/app.py        # Cyberpunk HUD
├── workspace/       # Isolated execution dir
├── audit_ledger/    # SHA-256 mission reports
├── cloud_bridge/    # SIEM-style export mirror
└── requirements.txt
```

---

## Design principles (aligned to A1)

1. **Never claim completion without evidence** — binary VERIFIED / REJECTED only after gates.
2. **Per-step verification** — each step has its own evidence spec.
3. **Detect + recover** — failures trigger heal + re-execute, not silent ignore.
4. **Zero-trust defaults** — static analysis before any code runs.
5. **Tamper-evident audit** — full mission hashed with SHA-256.

---

## Team note

Offline plans work fully without Gemini so judges can demo instantly. Toggle **Use Live Gemini Planner** when a key is configured for open-ended objectives.

---

## Intermittent Connectivity (Offline Resilience)

**Critical functions that work WITHOUT internet:**

| Function | Offline? |
|----------|----------|
| Offline planner (Fibonacci, Iris, buggy heal) | ✅ |
| AST security guardrails | ✅ |
| Sandbox execution | ✅ |
| Evidence gates | ✅ |
| Local audit ledger | ✅ |
| Outbox queue | ✅ |
| Offline self-heal heuristics | ✅ |
| Live Gemini planner / heal | ❌ (needs network) |

### Disconnect → Operate → Reconnect → Recover

1. Open **📡 Connectivity Lab** in the sidebar.
2. Click **Simulate Disconnect** (or unplug Wi‑Fi).
3. Run **B · ML Iris** or **C · Buggy ML** — full pipeline works offline.
4. Mission is saved to `audit_ledger/` and queued in `outbox/`.
5. Click **Simulate Reconnect**.
6. Click **Sync Outbox Now** — data reconciles into `cloud_bridge/`.
7. Open **📜 Mission History** → click any mission for the full report.

---

## Mission History

Every mission is indexed in `audit_ledger/history_index.json`.
Open **Mission History** in the UI, click a row, and view the complete
step evidence trail, heal attempts, hash, and downloadable JSON.
