"""
AegisFlow — Redesigned multi-dashboard UI
Mission | History | Connectivity Lab
Light + Dark themes · clear spacing · no clutter
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import json
import datetime

from agent.planner import (
    create_plan,
    offline_plan_fibonacci,
    offline_plan_ml_iris,
    offline_plan_ml_buggy,
)
from agent.offline_planner import plan_offline
from core.orchestrator import run_mission
from core.models import ExecutionPlan, PlanStep, StepAction, EvidenceSpec, EvidenceKind
from core.connectivity import (
    is_online,
    connectivity_status,
    sync_outbox,
    pending_count,
    load_history,
    load_mission_report,
)
from auth import service as auth_service

def has_gemini_key() -> bool:
    """True if GEMINI_API_KEY is available for scoring / live planning."""
    import os
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    return bool(key) and key not in ("paste_your_key_here", "your_key_here", "xxx")


# ═══════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="AegisFlow",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════
defaults = {
    "history": [],
    "last_report": None,
    "last_plan": None,
    "events": [],
    "force_offline": False,
    "selected_mission_id": None,
    "last_sync_result": None,
    "page": "Mission",
    "theme": "dark",
    # ── auth state ───────────────────────────────
    "authenticated": False,
    "auth_email": None,
    "auth_username": None,
    "auth_stage": "login",       # "login" | "otp" | "register"
    "auth_pending_email": None,
    "auth_error": None,
    "auth_info": None,
    "auth_dev_otp": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ═══════════════════════════════════════════════════════════
# THEMES
# ═══════════════════════════════════════════════════════════
DARK = {
    "bg": "#0b1220",
    "bg2": "#111827",
    "card": "#151c2c",
    "card_border": "rgba(99, 179, 237, 0.22)",
    "text": "#e8eef7",
    "muted": "#94a3b8",
    "accent": "#38bdf8",
    "accent2": "#a78bfa",
    "success": "#34d399",
    "danger": "#f87171",
    "warn": "#fbbf24",
    "sidebar": "#0a101c",
    "input_bg": "#0f172a",
    "gradient": "linear-gradient(135deg, #0b1220 0%, #121a2e 50%, #0d1526 100%)",
}

LIGHT = {
    "bg": "#f0f4f8",
    "bg2": "#e8eef5",
    "card": "#ffffff",
    "card_border": "rgba(14, 116, 144, 0.18)",
    "text": "#0f172a",
    "muted": "#64748b",
    "accent": "#0284c7",
    "accent2": "#7c3aed",
    "success": "#059669",
    "danger": "#dc2626",
    "warn": "#d97706",
    "sidebar": "#e2e8f0",
    "input_bg": "#ffffff",
    "gradient": "linear-gradient(135deg, #eef2ff 0%, #f0f9ff 40%, #f8fafc 100%)",
}

T = DARK if st.session_state.theme == "dark" else LIGHT

def inject_css(t: dict):
    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

html, body, [class*="css"] {{
    font-family: 'DM Sans', sans-serif;
}}

.stApp {{
    background: {t["gradient"]};
    color: {t["text"]};
}}

section[data-testid="stSidebar"] {{
    background: {t["sidebar"]} !important;
    border-right: 1px solid {t["card_border"]};
    padding: 1.25rem 1rem;
}}

section[data-testid="stSidebar"] * {{
    color: {t["text"]};
}}

.block-container {{
    padding: 2.25rem 2.25rem 2.5rem 2.25rem !important;
    max-width: 1280px;
}}

h1, h2, h3, h4 {{
    color: {t["text"]} !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em;
}}

.af-title {{
    font-size: 1.85rem;
    font-weight: 700;
    color: {t["text"]};
    margin: 0 0 0.25rem 0;
}}
.af-sub {{
    color: {t["muted"]};
    font-size: 0.95rem;
    margin: 0 0 1.5rem 0;
}}

.af-card {{
    background: {t["card"]};
    border: 1px solid {t["card_border"]};
    border-radius: 14px;
    padding: 1.25rem 1.35rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}}

.af-card-title {{
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: {t["muted"]};
    margin-bottom: 0.65rem;
}}

.af-kpi {{
    background: {t["card"]};
    border: 1px solid {t["card_border"]};
    border-radius: 12px;
    padding: 1rem 1.1rem;
    text-align: left;
}}
.af-kpi-label {{
    font-size: 0.75rem;
    color: {t["muted"]};
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.35rem;
}}
.af-kpi-value {{
    font-size: 1.35rem;
    font-weight: 700;
    color: {t["text"]};
    font-family: 'JetBrains Mono', monospace;
}}

.badge {{
    display: inline-block;
    border-radius: 6px;
    padding: 0.2rem 0.65rem;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.03em;
}}
.badge-ok {{ background: {t["success"]}22; color: {t["success"]}; border: 1px solid {t["success"]}55; }}
.badge-fail {{ background: {t["danger"]}22; color: {t["danger"]}; border: 1px solid {t["danger"]}55; }}
.badge-heal {{ background: {t["warn"]}22; color: {t["warn"]}; border: 1px solid {t["warn"]}55; }}
.badge-block {{ background: {t["danger"]}22; color: {t["danger"]}; border: 1px solid {t["danger"]}55; }}
.badge-net-on {{ background: {t["success"]}22; color: {t["success"]}; border: 1px solid {t["success"]}55; }}
.badge-net-off {{ background: {t["warn"]}22; color: {t["warn"]}; border: 1px solid {t["warn"]}55; }}

.step-item {{
    border-left: 3px solid {t["accent"]};
    padding: 0.55rem 0 0.55rem 0.9rem;
    margin: 0.4rem 0 0.7rem 0;
}}
.step-id {{
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
    color: {t["accent"]};
    font-size: 0.9rem;
}}
.step-meta {{
    color: {t["muted"]};
    font-size: 0.82rem;
    margin-top: 0.2rem;
}}

.hash-box {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
    color: {t["accent"]};
    word-break: break-all;
    background: {t["bg2"]};
    border: 1px solid {t["card_border"]};
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin: 0.5rem 0 1rem 0;
}}

.hist-row {{
    background: {t["card"]};
    border: 1px solid {t["card_border"]};
    border-radius: 10px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.6rem;
}}

/* Streamlit bordered containers = our 4 blocks */
div[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {t["card"]} !important;
    border: 1px solid {t["card_border"]} !important;
    border-radius: 14px !important;
    padding: 1rem 1.15rem 1.15rem 1.15rem !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"] p,
div[data-testid="stVerticalBlockBorderWrapper"] span,
div[data-testid="stVerticalBlockBorderWrapper"] label {{
    color: {t["text"]} !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"] .stCaption,
div[data-testid="stVerticalBlockBorderWrapper"] small {{
    color: {t["muted"]} !important;
}}
code {{
    color: {t["accent"]} !important;
    background: {t["bg2"]} !important;
}}
.stMarkdown, .stMarkdown p, .stMarkdown li {{
    color: {t["text"]} !important;
}}
.stCaption, [data-testid="stCaptionContainer"] {{
    color: {t["muted"]} !important;
}}


div[data-testid="stMetric"] {{
    background: {t["card"]};
    border: 1px solid {t["card_border"]};
    border-radius: 12px;
    padding: 0.85rem 1rem;
}}
div[data-testid="stMetric"] label {{
    color: {t["muted"]} !important;
}}

.stButton > button {{
    border-radius: 10px !important;
    font-weight: 600 !important;
    padding: 0.5rem 1rem !important;
}}

hr {{
    border-color: {t["card_border"]} !important;
    margin: 1.25rem 0 !important;
}}

footer {{ visibility: hidden; }}
#MainMenu {{ visibility: hidden; }}
header[data-testid="stHeader"] {{
    visibility: hidden;
    height: 0 !important;
    min-height: 0 !important;
}}
div[data-testid="stToolbar"] {{ visibility: hidden; }}
div[data-testid="stDecoration"] {{ visibility: hidden; }}
.stApp > header {{ height: 0 !important; }}
</style>
""", unsafe_allow_html=True)

inject_css(T)

# ═══════════════════════════════════════════════════════════
# AUTH GATE — login + OTP email verification
# Nothing below this block renders until st.session_state.authenticated
# is True. See auth/service.py for the underlying logic.
# ═══════════════════════════════════════════════════════════
def _auth_feedback():
    if st.session_state.auth_error:
        st.error(st.session_state.auth_error)
        st.session_state.auth_error = None
    if st.session_state.auth_info:
        st.success(st.session_state.auth_info)
        st.session_state.auth_info = None
    if st.session_state.auth_dev_otp:
        st.warning(
            f"🧪 DEV MODE (SMTP not configured) — your code is **{st.session_state.auth_dev_otp}**"
        )


def render_login_page():
    st.markdown('<div class="af-title">🛡️ AegisFlow</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="af-sub">Mission Control is locked. Sign in to continue.</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([1, 1.1], gap="large")

    # ── LEFT: brand / feature blocks ───────────────────────────
    with left:
        st.markdown(
            f"""
<div class="af-card" style="margin-bottom:1rem;">
    <span class="badge badge-net-on">🔒 OTP EMAIL VERIFICATION</span>
    <div style="margin-top:0.9rem; font-size:1.05rem; font-weight:700; color:{T['text']};">
        Every login is a two-step mission.
    </div>
    <div style="margin-top:0.4rem; color:{T['muted']}; font-size:0.9rem; line-height:1.5;">
        Password checked first, then a one-time code is emailed to your
        registered address before Mission Control unlocks — same
        zero-trust standard the agent pipeline holds itself to.
    </div>
</div>
""",
            unsafe_allow_html=True,
        )

        features = [
            ("🔑", "Salted & hashed", "Passwords never stored in plaintext (PBKDF2-SHA256)."),
            ("📧", "Email-verified", "A fresh 6-digit code is required on every login."),
            ("⏱️", "Auto-expiring codes", "Codes expire in 5 minutes and lock after 5 tries."),
            ("🧾", "Audited access", "Every mission you run is hashed to the audit ledger."),
        ]
        fcols = st.columns(2)
        for i, (icon, title, desc) in enumerate(features):
            with fcols[i % 2]:
                st.markdown(
                    f"""
<div class="af-kpi" style="margin-bottom:0.75rem; min-height:118px;">
    <div style="font-size:1.3rem;">{icon}</div>
    <div class="af-kpi-label" style="margin-top:0.4rem;">{title}</div>
    <div style="color:{T['muted']}; font-size:0.78rem; margin-top:0.2rem; line-height:1.35;">{desc}</div>
</div>
""",
                    unsafe_allow_html=True,
                )

    # ── RIGHT: the actual form card ─────────────────────────────
    with right:
        with st.container(border=True):

            # ── STAGE: enter email + password ─────────────────
            if st.session_state.auth_stage == "login":
                st.markdown(
                    f'<div class="af-card-title">STEP 1 OF 2 · CREDENTIALS</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("#### 👋 Log in")
                with st.form("login_form", clear_on_submit=False):
                    email = st.text_input("📧 Email", key="login_email", placeholder="you@example.com")
                    password = st.text_input("🔑 Password", type="password", key="login_password", placeholder="••••••••")
                    submitted = st.form_submit_button("Continue →", use_container_width=True)
                if submitted:
                    result = auth_service.start_login(email, password)
                    if result.ok:
                        st.session_state.auth_pending_email = auth_service.user_store.normalize_email(email)
                        st.session_state.auth_stage = "otp"
                        st.session_state.auth_info = "Verification code sent to your email."
                        st.session_state.auth_dev_otp = result.dev_otp
                        st.rerun()
                    else:
                        st.session_state.auth_error = result.message
                        st.rerun()

                _auth_feedback()
                st.markdown("<hr>", unsafe_allow_html=True)
                c1, c2 = st.columns([1.4, 1])
                with c1:
                    st.caption("Don't have an account yet?")
                with c2:
                    if st.button("Create one", use_container_width=True):
                        st.session_state.auth_stage = "register"
                        st.rerun()

            # ── STAGE: enter OTP ───────────────────────────────
            elif st.session_state.auth_stage == "otp":
                st.markdown(
                    '<div class="af-card-title">STEP 2 OF 2 · EMAIL VERIFICATION</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("#### 📨 Enter verification code")
                st.caption(f"We sent a 6-digit code to **{st.session_state.auth_pending_email}**.")
                _auth_feedback()

                with st.form("otp_form", clear_on_submit=False):
                    code = st.text_input(
                        "6-digit code", max_chars=6, key="otp_code", placeholder="000000"
                    )
                    verify = st.form_submit_button("Verify & log in ✅", use_container_width=True)
                if verify:
                    result = auth_service.complete_login(st.session_state.auth_pending_email, code)
                    if result.ok:
                        st.session_state.authenticated = True
                        st.session_state.auth_email = st.session_state.auth_pending_email
                        user = auth_service.user_store.get_user(st.session_state.auth_email)
                        st.session_state.auth_username = user["username"] if user else st.session_state.auth_email
                        st.session_state.auth_stage = "login"
                        st.session_state.auth_pending_email = None
                        st.session_state.auth_dev_otp = None
                        st.rerun()
                    else:
                        st.session_state.auth_error = result.message
                        st.rerun()

                st.markdown("<hr>", unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("↻ Resend code", use_container_width=True):
                        r = auth_service.resend_login_otp(st.session_state.auth_pending_email)
                        st.session_state.auth_info = r.message if r.ok else None
                        st.session_state.auth_error = None if r.ok else r.message
                        st.session_state.auth_dev_otp = r.dev_otp
                        st.rerun()
                with c2:
                    if st.button("← Back", use_container_width=True):
                        st.session_state.auth_stage = "login"
                        st.session_state.auth_pending_email = None
                        st.session_state.auth_dev_otp = None
                        st.rerun()
                return  # feedback already rendered above the form for this stage

            # ── STAGE: register ────────────────────────────────
            elif st.session_state.auth_stage == "register":
                st.markdown(
                    '<div class="af-card-title">CREATE ACCOUNT</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("#### ✨ Join AegisFlow")
                with st.form("register_form", clear_on_submit=False):
                    username = st.text_input("👤 Username", key="reg_username")
                    email = st.text_input("📧 Email", key="reg_email", placeholder="you@example.com")
                    password = st.text_input("🔑 Password", type="password", key="reg_password", placeholder="min. 8 characters")
                    confirm = st.text_input("🔑 Confirm password", type="password", key="reg_confirm")
                    submitted = st.form_submit_button("Create account", use_container_width=True)
                if submitted:
                    result = auth_service.register_user(username, email, password, confirm)
                    if result.ok:
                        st.session_state.auth_stage = "login"
                        st.session_state.auth_info = result.message
                    else:
                        st.session_state.auth_error = result.message
                    st.rerun()

                _auth_feedback()
                st.markdown("<hr>", unsafe_allow_html=True)
                c1, c2 = st.columns([1.4, 1])
                with c1:
                    st.caption("Already have an account?")
                with c2:
                    if st.button("Back to login", use_container_width=True):
                        st.session_state.auth_stage = "login"
                        st.rerun()


if not st.session_state.authenticated:
    render_login_page()
    st.stop()

# ═══════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🛡️ AegisFlow")
    st.caption("Zero-trust agent workflow")

    st.markdown("---")
    st.markdown(f"**{st.session_state.auth_username or st.session_state.auth_email}**")
    st.caption(st.session_state.auth_email)
    if st.button("Log out", use_container_width=True):
        for k in ("authenticated", "auth_email", "auth_username", "auth_pending_email", "auth_dev_otp"):
            st.session_state[k] = defaults[k]
        st.session_state.auth_stage = "login"
        st.rerun()

    st.markdown("---")
    page = st.radio(
        "Dashboards",
        ["Mission", "History", "Connectivity Lab"],
        index=["Mission", "History", "Connectivity Lab"].index(st.session_state.page)
        if st.session_state.page in ["Mission", "History", "Connectivity Lab"] else 0,
        label_visibility="collapsed",
    )
    st.session_state.page = page

    st.markdown("---")
    theme_choice = st.radio(
        "Theme",
        ["Dark", "Light"],
        index=0 if st.session_state.theme == "dark" else 1,
        horizontal=True,
    )
    new_theme = "dark" if theme_choice == "Dark" else "light"
    if new_theme != st.session_state.theme:
        st.session_state.theme = new_theme
        st.rerun()

    st.markdown("---")
    real_online = is_online()
    effective_online = real_online and not st.session_state.force_offline
    if effective_online:
        st.markdown('<span class="badge badge-net-on">● ONLINE</span>', unsafe_allow_html=True)
    else:
        label = "SIMULATED" if st.session_state.force_offline else "NO NETWORK"
        st.markdown(f'<span class="badge badge-net-off">● OFFLINE — {label}</span>', unsafe_allow_html=True)

    pending = pending_count()
    if pending:
        st.caption(f"Outbox pending: {pending}")

# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
def kpi_row(report, effective_online, pending):
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(
            f'<div class="af-kpi"><div class="af-kpi-label">Network</div>'
            f'<div class="af-kpi-value">{"Online" if effective_online else "Offline"}</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        status = "Standby"
        if report is not None:
            status = "Verified" if report.success else "Failed"
        st.markdown(
            f'<div class="af-kpi"><div class="af-kpi-label">Mission</div>'
            f'<div class="af-kpi-value">{status}</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div class="af-kpi"><div class="af-kpi-label">Self-Heals</div>'
            f'<div class="af-kpi-value">{report.heal_count if report else 0}</div></div>',
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f'<div class="af-kpi"><div class="af-kpi-label">Blocks</div>'
            f'<div class="af-kpi-value">{report.security_blocks if report else 0}</div></div>',
            unsafe_allow_html=True,
        )
    with c5:
        st.markdown(
            f'<div class="af-kpi"><div class="af-kpi-label">Outbox</div>'
            f'<div class="af-kpi-value">{pending}</div></div>',
            unsafe_allow_html=True,
        )


def render_plan(plan, offline_tag=False):
    tag = ' <span class="badge badge-net-off">OFFLINE PLAN</span>' if offline_tag else ""
    st.markdown(
        f'<div class="af-card"><div class="af-card-title">Execution Plan</div>'
        f'<div style="margin-bottom:0.75rem;"><b>Objective</b><br/>{plan.objective}</div>'
        f'<div style="color:{T["muted"]};font-size:0.85rem;">Domain: <code>{plan.domain}</code> · Steps: {len(plan.steps)}{tag}</div></div>',
        unsafe_allow_html=True,
    )
    for s in plan.steps:
        ev = s.evidence
        ev_txt = ev.kind.value
        if ev.metric_key:
            ev_txt += f" · {ev.metric_key} ≥ {ev.threshold}"
        elif ev.expected:
            ev_txt += f" · “{ev.expected}”"
        st.markdown(
            f'<div class="step-item">'
            f'<span class="step-id">{s.id}</span> · <code>{s.action.value}</code><br/>'
            f'{s.description or s.file or s.command or ""}'
            f'<div class="step-meta">Evidence: {ev_txt}</div></div>',
            unsafe_allow_html=True,
        )


def render_evidence(report):
    st.markdown('<div class="af-card-title">Step Evidence</div>', unsafe_allow_html=True)
    for rec in report.steps:
        status = rec.status.value
        badge_cls = {
            "verified": "badge-ok",
            "guardrail_blocked": "badge-block",
            "rejected": "badge-fail",
            "healing": "badge-heal",
        }.get(status, "badge-fail")
        heal = ' <span class="badge badge-heal">SELF-HEALED</span>' if rec.healed else ""
        reason = rec.final_evidence.reason if rec.final_evidence else "—"
        st.markdown(
            f'<div class="af-card">'
            f'<span class="badge {badge_cls}">{status.upper()}</span>{heal}'
            f'&nbsp;&nbsp;<b>{rec.step.id}</b> <code>{rec.step.action.value}</code>'
            f'<div class="step-meta" style="margin-top:0.5rem;">{reason}</div></div>',
            unsafe_allow_html=True,
        )
        with st.expander(f"Attempts — {rec.step.id} ({len(rec.attempts)})"):
            st.json(rec.attempts)


def render_verdict(report, effective_online):
    if report.success:
        st.markdown(
            f'<div class="af-card"><span class="badge badge-ok">MISSION VERIFIED</span>'
            f'<p style="margin:0.75rem 0 0 0;color:{T["muted"]};">All steps passed machine-checkable evidence gates.</p></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="af-card"><span class="badge badge-fail">NOT VERIFIED</span>'
            f'<p style="margin:0.75rem 0 0 0;color:{T["muted"]};">Pipeline halted. Success was not claimed.</p></div>',
            unsafe_allow_html=True,
        )
    st.markdown('<div class="af-card-title">Audit Ledger</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="hash-box">{report.ledger_hash}</div>', unsafe_allow_html=True)
    st.caption(f"ID: {report.mission_id}")
    st.caption(f"{report.started_at} → {report.finished_at}")
    st.download_button(
        "Download audit JSON",
        data=json.dumps(report.to_dict(), indent=2),
        file_name=f"{report.mission_id}_audit.json",
        mime="application/json",
        use_container_width=True,
    )
    if effective_online:
        st.success("Saved to audit_ledger and cloud_bridge.")
    else:
        st.warning("Saved locally and queued in outbox for sync.")


# ═══════════════════════════════════════════════════════════
# PAGE: MISSION
# ═══════════════════════════════════════════════════════════
if st.session_state.page == "Mission":
    st.markdown('<p class="af-title">Mission Control</p>', unsafe_allow_html=True)
    st.markdown('<p class="af-sub">Plan · secure · execute · verify · audit</p>', unsafe_allow_html=True)

    real_online = is_online()
    effective_online = real_online and not st.session_state.force_offline
    pending = pending_count()
    kpi_row(st.session_state.last_report, effective_online, pending)
    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    # Controls in a clean card row
    left, right = st.columns([1.1, 1], gap="large")

    with left:
        st.markdown('<div class="af-card-title">Mission setup</div>', unsafe_allow_html=True)
        preset = st.selectbox(
            "Scenario",
            [
                "Custom Objective",
                "A · Fibonacci",
                "B · ML Iris",
                "C · Buggy ML + Self-Heal",
                "D · Security Guardrail",
            ],
        )
        defaults_obj = {
            "A · Fibonacci": "Create a Python Fibonacci function and verify that Fibonacci(30) = 832040",
            "B · ML Iris": "Train a logistic regression on Iris dataset and verify accuracy >= 0.90",
            "C · Buggy ML + Self-Heal": "Train Iris model with intentional bug — self-heal and verify accuracy >= 0.85",
            "D · Security Guardrail": "Write a script that uses os.system('ls') — should be blocked",
            "Custom Objective": "Train a model on Iris and report accuracy as JSON with threshold 0.90",
        }
        objective = st.text_area(
            "Objective",
            defaults_obj.get(preset, defaults_obj["Custom Objective"]),
            height=110,
        )

        gemini_ready = has_gemini_key() and effective_online

        if gemini_ready:
            st.success("Gemini API key detected — live planner available (counts for evaluation).")
        elif not has_gemini_key():
            st.warning("No GEMINI_API_KEY in .env — offline planner only. Add key for full marks.")
        elif not effective_online:
            st.caption("Offline — local planner and local heal only.")

        c_a, c_b = st.columns(2)
        with c_a:
            use_live = st.toggle(
                "Live Gemini planner",
                value=gemini_ready,  # ON by default when key + online
                disabled=not effective_online or not has_gemini_key(),
                help="Uses Google Gemini to plan custom objectives. Recommended when API key is set.",
            )
        with c_b:
            use_heal = st.toggle(
                "Gemini self-heal",
                value=gemini_ready,
                disabled=not effective_online or not has_gemini_key(),
                help="Uses Gemini to repair failed steps. Offline heuristics still run as backup.",
            )

        block_input = st.text_input(
            "Extra blocked tokens",
            "os.system, subprocess, eval, exec",
        )
        extra_block = [x.strip() for x in block_input.split(",") if x.strip()]

        fo = st.toggle("Force offline mode", value=st.session_state.force_offline)
        if fo != st.session_state.force_offline:
            st.session_state.force_offline = fo
            st.rerun()

        run = st.button("Execute mission", type="primary", use_container_width=True)

        if run:
            st.session_state.events = []

            def on_event(name, payload):
                st.session_state.events.append({"event": name, **payload})

            with st.spinner("Running pipeline…"):
                try:
                    # Use Gemini whenever: online + key + toggle ON + not force-offline
                    use_gemini_now = (
                        use_live
                        and effective_online
                        and has_gemini_key()
                        and not st.session_state.force_offline
                    )
                    if not use_gemini_now:
                        if preset.startswith("A") or "fibonacci" in objective.lower():
                            plan = offline_plan_fibonacci()
                        elif preset.startswith("C") or (
                            "buggy" in objective.lower() and "self-heal" in objective.lower()
                        ):
                            plan = offline_plan_ml_buggy()
                        elif preset.startswith("D") or "os.system" in objective.lower():
                            plan = ExecutionPlan(
                                objective=objective,
                                domain="general",
                                steps=[
                                    PlanStep(
                                        id="S1",
                                        action=StepAction.CREATE_FILE,
                                        description="Malicious script",
                                        file="bad.py",
                                        content="import os\nos.system('ls')\nprint('pwned')\n",
                                        evidence=EvidenceSpec(kind=EvidenceKind.NONE),
                                    ),
                                    PlanStep(
                                        id="S2",
                                        action=StepAction.RUN_PYTHON,
                                        description="Run",
                                        file="bad.py",
                                        evidence=EvidenceSpec(kind=EvidenceKind.EXIT_ZERO),
                                    ),
                                ],
                            )
                        elif preset.startswith("B"):
                            plan = offline_plan_ml_iris()
                        else:
                            plan = plan_offline(objective)
                    else:
                        plan = create_plan(objective)

                    st.session_state.last_plan = plan
                    report = run_mission(
                        plan,
                        extra_blocklist=extra_block,
                        use_gemini_heal=use_heal and effective_online,
                        event_cb=on_event,
                    )
                    st.session_state.last_report = report
                    st.session_state.history.append(
                        {
                            "mission_id": report.mission_id,
                            "objective": report.objective,
                            "success": report.success,
                            "hash": report.ledger_hash,
                            "connectivity": "online" if effective_online else "offline",
                        }
                    )
                except Exception as e:
                    st.error(f"Mission aborted: {e}")
                    st.session_state.last_report = None

    with right:
        st.markdown(
            f'<div class="af-card"><div class="af-card-title">Pipeline overview</div>'
            f'<p style="color:{T["muted"]};margin:0;line-height:1.65;">'
            f'<b>1. Planner</b> → structured steps<br/>'
            f'<b>2. Guardrails</b> → block unsafe code<br/>'
            f'<b>3. Sandbox + Heal</b> → run & recover<br/>'
            f'<b>4. Evidence + Audit</b> → prove & seal'
            f'</p></div>',
            unsafe_allow_html=True,
        )
        if st.session_state.last_report:
            render_verdict(st.session_state.last_report, effective_online)
        else:
            st.markdown(
                f'<div class="af-card"><div class="af-card-title">Verdict</div>'
                f'<p style="color:{T["muted"]};margin:0;">Execute a mission to fill the four blocks below.</p></div>',
                unsafe_allow_html=True,
            )

    # ── Four architecture blocks (full width) ──
    st.markdown("<div style='height:1.25rem'></div>", unsafe_allow_html=True)
    st.markdown("### Core pipeline")
    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    plan = st.session_state.last_plan
    report = st.session_state.last_report

    b1, b2 = st.columns(2, gap="large")

    # ════ BLOCK 1 — PLANNER ════
    with b1:
        with st.container(border=True):
            st.markdown("**1 · AI Planner**")
            if plan:
                st.markdown(f"**Objective**")
                st.write(plan.objective)
                st.caption(f"Domain: `{plan.domain}` · {len(plan.steps)} step(s)")
                for s in plan.steps:
                    ev = s.evidence
                    ev_txt = ev.kind.value
                    if ev.metric_key:
                        ev_txt += f" · {ev.metric_key} ≥ {ev.threshold}"
                    elif ev.expected:
                        ev_txt += f" · {ev.expected}"
                    st.markdown(f"**{s.id}** · `{s.action.value}`")
                    st.caption(f"{s.description or s.file or s.command or '—'}")
                    st.caption(f"Evidence: {ev_txt}")
            else:
                st.caption("Parses the objective into ordered steps with evidence rules.")

    # ════ BLOCK 2 — GUARDRAILS ════
    with b2:
        with st.container(border=True):
            st.markdown("**2 · Security Guardrails**")
            if report:
                blocks = report.security_blocks
                if blocks:
                    st.error(f"BLOCKED × {blocks}")
                    for rec in report.steps:
                        if rec.status.value == "guardrail_blocked":
                            reason = rec.final_evidence.reason if rec.final_evidence else "Policy violation"
                            st.write(f"**{rec.step.id}** — {reason}")
                else:
                    st.success("NO VIOLATIONS")
                    st.caption("AST scan cleared all payloads before execution.")
            else:
                st.caption("Static analysis blocks eval, exec, os.system, subprocess before any code runs.")

    b3, b4 = st.columns(2, gap="large")

    # ════ BLOCK 3 — SANDBOX + HEAL ════
    with b3:
        with st.container(border=True):
            st.markdown("**3 · Sandbox & Self-Heal**")
            if report:
                heals = report.heal_count
                if heals:
                    st.warning(f"HEALED × {heals}")
                else:
                    st.success("CLEAN RUN")
                for rec in report.steps:
                    attempts = len(rec.attempts)
                    tag = " · self-healed" if rec.healed else ""
                    st.write(f"**{rec.step.id}** · `{rec.status.value}` · {attempts} attempt(s){tag}")
                st.caption("Timed workspace execution. Failures trigger heal + retry.")
            else:
                st.caption("Runs code in an isolated workspace. On crash or bad evidence, heals and retries.")

    # ════ BLOCK 4 — EVIDENCE + AUDIT ════
    with b4:
        with st.container(border=True):
            st.markdown("**4 · Evidence Gate & Audit**")
            if report:
                if report.success:
                    st.success("ALL GATES PASSED")
                else:
                    st.error("GATE FAILED")
                for rec in report.steps:
                    if rec.final_evidence:
                        st.write(f"**{rec.step.id}** — {rec.final_evidence.reason}")
                st.code(report.ledger_hash, language=None)
                st.caption("Machine-checkable proof + SHA-256 ledger.")
            else:
                st.caption("Verifies exact values, numeric thresholds, or JSON metrics. Seals the mission with SHA-256.")

    if st.session_state.last_report:
        with st.expander("Full evidence trail & attempts"):
            render_evidence(st.session_state.last_report)
        with st.expander("Event stream"):
            for ev in st.session_state.events[-15:]:
                st.caption(f"`{ev.get('event')}` · { {k: v for k, v in ev.items() if k != 'event'} }")

# ═══════════════════════════════════════════════════════════
# PAGE: HISTORY
# ═══════════════════════════════════════════════════════════
elif st.session_state.page == "History":
    st.markdown('<p class="af-title">Mission History</p>', unsafe_allow_html=True)
    st.markdown('<p class="af-sub">Every mission is stored locally — available offline</p>', unsafe_allow_html=True)

    # Detail view
    if st.session_state.selected_mission_id:
        mid = st.session_state.selected_mission_id
        if st.button("← Back to list"):
            st.session_state.selected_mission_id = None
            st.rerun()

        st.markdown(f"### Mission Report")
        st.caption(mid)
        full = load_mission_report(mid)
        if not full:
            st.error("Report file not found.")
        else:
            # Verdict banner
            if full.get("success"):
                st.success("MISSION VERIFIED — all evidence gates passed")
            else:
                st.error("MISSION NOT VERIFIED — success was not claimed")

            # Objective showcase
            with st.container(border=True):
                st.markdown("**Objective**")
                st.write(full.get("objective") or "—")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Domain", full.get("domain") or "—")
                c2.metric("Heals", full.get("heal_count", 0))
                c3.metric("Blocks", full.get("security_blocks", 0))
                c4.metric("Steps", len(full.get("steps") or []))
                st.caption(
                    f"{full.get('started_at', '')} → {full.get('finished_at', '')} · "
                    f"Connectivity: {full.get('connectivity_at_finish', 'n/a')}"
                )

            st.markdown("#### What the system did")
            for step_rec in full.get("steps", []):
                step = step_rec.get("step", {}) or {}
                st_status = step_rec.get("status", "")
                ev = step_rec.get("final_evidence") or {}
                attempts = step_rec.get("attempts") or []

                with st.container(border=True):
                    # Status line
                    if st_status == "verified":
                        st.success(f"{step.get('id', '?')} · {step.get('action', '')} · VERIFIED")
                    elif st_status == "guardrail_blocked":
                        st.error(f"{step.get('id', '?')} · {step.get('action', '')} · BLOCKED")
                    elif st_status == "rejected":
                        st.error(f"{step.get('id', '?')} · {step.get('action', '')} · REJECTED")
                    else:
                        st.warning(f"{step.get('id', '?')} · {step.get('action', '')} · {st_status.upper()}")

                    if step_rec.get("healed"):
                        st.warning("Self-healed on a later attempt")

                    st.markdown(f"**Description:** {step.get('description') or '—'}")
                    if step.get("file"):
                        st.markdown(f"**File:** `{step.get('file')}`")
                    if step.get("command"):
                        st.markdown(f"**Command:** `{step.get('command')}`")

                    # Generated code / content
                    content = step.get("content")
                    if content:
                        st.markdown("**Generated code**")
                        st.code(content, language="python")

                    # Evidence result
                    st.markdown(f"**Evidence:** {ev.get('reason') or '—'}")

                    # Attempt outputs (stdout / errors from model run)
                    if attempts:
                        with st.expander(f"Run attempts ({len(attempts)}) — stdout / errors"):
                            for i, att in enumerate(attempts, 1):
                                st.markdown(f"**Attempt {i}**")
                                if isinstance(att, dict):
                                    if att.get("stdout"):
                                        st.markdown("Stdout:")
                                        st.code(str(att.get("stdout"))[:3000])
                                    if att.get("stderr"):
                                        st.markdown("Stderr:")
                                        st.code(str(att.get("stderr"))[:2000])
                                    if att.get("reason"):
                                        st.caption(att.get("reason"))
                                    if att.get("verified") is not None:
                                        st.caption(f"Verified: {att.get('verified')}")
                                else:
                                    st.json(att)

            # Audit
            st.markdown("#### Cryptographic audit")
            st.code(full.get("ledger_hash") or "—", language=None)

            st.download_button(
                "Download full report JSON",
                data=json.dumps(full, indent=2),
                file_name=f"{mid}_report.json",
                mime="application/json",
                use_container_width=True,
            )
    else:
        history = load_history()
        seen = {h.get("mission_id") for h in history}
        for h in st.session_state.history:
            if h.get("mission_id") not in seen:
                history.append(h)

        if not history:
            st.markdown(
                f'<div class="af-card"><p style="color:{T["muted"]};margin:0;">'
                f'No missions yet. Run one from the Mission dashboard.</p></div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption(f"{len(history)} mission(s)")
            for h in reversed(history):
                mid = h.get("mission_id", "?")
                ok = h.get("success")
                icon = "✓" if ok else "✗"
                conn = h.get("connectivity", "—")
                obj = str(h.get("objective", ""))[:70]
                cols = st.columns([0.08, 0.62, 0.18, 0.12])
                with cols[0]:
                    st.markdown(f"**{icon}**")
                with cols[1]:
                    st.markdown(f"`{mid}`  \n{obj}")
                with cols[2]:
                    st.caption(conn)
                with cols[3]:
                    if st.button("Open", key=f"open_{mid}", use_container_width=True):
                        st.session_state.selected_mission_id = mid
                        st.rerun()
                st.markdown(
                    f'<div style="height:1px;background:{T["card_border"]};margin:0.4rem 0 0.7rem 0;"></div>',
                    unsafe_allow_html=True,
                )

# ═══════════════════════════════════════════════════════════
# PAGE: CONNECTIVITY LAB
# ═══════════════════════════════════════════════════════════
elif st.session_state.page == "Connectivity Lab":
    st.markdown('<p class="af-title">Connectivity Lab</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="af-sub">Offline operation · outbox queue · automatic sync</p>',
        unsafe_allow_html=True,
    )

    real_online = is_online()
    effective_online = real_online and not st.session_state.force_offline
    status = connectivity_status()
    pending = pending_count()

    # Status cards
    a, b, c = st.columns(3, gap="medium")
    with a:
        st.markdown(
            f'<div class="af-card"><div class="af-card-title">Network probe</div>'
            f'<div class="af-kpi-value">{"Online" if real_online else "Offline"}</div></div>',
            unsafe_allow_html=True,
        )
    with b:
        st.markdown(
            f'<div class="af-card"><div class="af-card-title">Effective mode</div>'
            f'<div class="af-kpi-value">{"Online" if effective_online else "Offline"}</div>'
            f'<div class="step-meta">Forced: {st.session_state.force_offline}</div></div>',
            unsafe_allow_html=True,
        )
    with c:
        st.markdown(
            f'<div class="af-card"><div class="af-card-title">Outbox pending</div>'
            f'<div class="af-kpi-value">{pending}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    # Actions
    st.markdown('<div class="af-card-title">Actions</div>', unsafe_allow_html=True)
    d1, d2, d3 = st.columns(3, gap="medium")
    with d1:
        if st.button("Simulate disconnect", use_container_width=True):
            st.session_state.force_offline = True
            st.rerun()
    with d2:
        if st.button("Simulate reconnect", use_container_width=True):
            st.session_state.force_offline = False
            st.rerun()
    with d3:
        if st.button("Sync outbox", type="primary", use_container_width=True):
            if is_online() and not st.session_state.force_offline:
                result = sync_outbox()
                st.session_state.last_sync_result = result
                st.success(f"Synced {result['synced_count']} item(s). Remaining: {result['remaining']}")
            else:
                st.warning("Still offline — reconnect first.")

    st.markdown("<div style='height:0.75rem'></div>", unsafe_allow_html=True)

    # Critical offline functions
    st.markdown(
        f'<div class="af-card"><div class="af-card-title">Critical offline functions</div>'
        f'<ul style="margin:0.25rem 0 0 1.1rem;color:{T["text"]};line-height:1.7;">'
        + "".join(f"<li>{fn}</li>" for fn in status["critical_offline_functions"])
        + "</ul></div>",
        unsafe_allow_html=True,
    )

    if st.session_state.last_sync_result:
        with st.expander("Last sync details"):
            st.json(st.session_state.last_sync_result)

    st.caption(f"Last probe: {status['checked_at']}")

# Footer
st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)
st.caption(
    f"AegisFlow · Evidence-gated · Offline-capable · {datetime.datetime.now().strftime('%Y-%m-%d')}"
)
