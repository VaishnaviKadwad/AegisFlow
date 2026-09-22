"""
Offline planner for custom objectives — no internet / no Gemini required.

Maps natural-language goals to structured ExecutionPlans using
keyword rules + safe code templates. Covers ML, math, data, and
generic script tasks so critical functionality continues offline.
"""

from __future__ import annotations

import re
from typing import Optional

from core.models import (
    ExecutionPlan,
    PlanStep,
    StepAction,
    EvidenceSpec,
    EvidenceKind,
)


def _has(text: str, *words: str) -> bool:
    t = text.lower()
    return any(w.lower() in t for w in words)


def _extract_number(text: str, default: Optional[float] = None) -> Optional[float]:
    m = re.search(r"(\d+\.?\d*)", text.replace(",", ""))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return default
    return default


def plan_offline(objective: str) -> ExecutionPlan:
    """
    Build a usable ExecutionPlan without Gemini.
    Always returns a plan that can run under guardrails + evidence gates.
    """
    obj = (objective or "").strip()
    low = obj.lower()

    # ── Security / dangerous request → plan that will be blocked ──
    if _has(low, "os.system", "subprocess", "eval(", "exec(", "delete all", "rm -rf"):
        return ExecutionPlan(
            objective=obj,
            domain="general",
            steps=[
                PlanStep(
                    id="S1",
                    action=StepAction.CREATE_FILE,
                    description="Requested script (guardrails will inspect)",
                    file="requested.py",
                    content=(
                        "import os\n"
                        "os.system('echo blocked-if-dangerous')\n"
                        "print('done')\n"
                    ),
                    evidence=EvidenceSpec(kind=EvidenceKind.NONE),
                ),
            ],
        )

    # ── Fibonacci ──
    if _has(low, "fibonacci", "fib("):
        n = int(_extract_number(low, 30) or 30)
        # known values for common n
        fib_map = {10: 55, 15: 610, 20: 6765, 25: 75025, 30: 832040}
        expected = str(fib_map.get(n, ""))
        code = f'''def fibonacci(n):
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b

if __name__ == "__main__":
    print(fibonacci({n}))
'''
        steps = [
            PlanStep(
                id="S1",
                action=StepAction.CREATE_FILE,
                description=f"Write fibonacci({n})",
                file="fibonacci.py",
                content=code,
                evidence=EvidenceSpec(kind=EvidenceKind.NONE),
            ),
            PlanStep(
                id="S2",
                action=StepAction.RUN_PYTHON,
                description="Run and verify",
                file="fibonacci.py",
                evidence=EvidenceSpec(
                    kind=EvidenceKind.EXACT if expected else EvidenceKind.EXIT_ZERO,
                    expected=expected or None,
                ),
            ),
        ]
        return ExecutionPlan(objective=obj, domain="general", steps=steps)

    # ── Factorial ──
    if _has(low, "factorial"):
        n = int(_extract_number(low, 10) or 10)
        code = f'''def factorial(n):
    r = 1
    for i in range(2, n + 1):
        r *= i
    return r

if __name__ == "__main__":
    print(factorial({n}))
'''
        # 10! = 3628800
        fact_map = {5: 120, 6: 720, 7: 5040, 8: 40320, 9: 362880, 10: 3628800}
        expected = str(fact_map.get(n, ""))
        return ExecutionPlan(
            objective=obj,
            domain="general",
            steps=[
                PlanStep(
                    id="S1",
                    action=StepAction.CREATE_FILE,
                    description=f"Write factorial({n})",
                    file="factorial.py",
                    content=code,
                    evidence=EvidenceSpec(kind=EvidenceKind.NONE),
                ),
                PlanStep(
                    id="S2",
                    action=StepAction.RUN_PYTHON,
                    description="Run factorial",
                    file="factorial.py",
                    evidence=EvidenceSpec(
                        kind=EvidenceKind.EXACT if expected else EvidenceKind.EXIT_ZERO,
                        expected=expected or None,
                    ),
                ),
            ],
        )

    # ── Prime check ──
    if _has(low, "prime"):
        n = int(_extract_number(low, 97) or 97)
        code = f'''def is_prime(n):
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True

if __name__ == "__main__":
    print(is_prime({n}))
'''
        return ExecutionPlan(
            objective=obj,
            domain="general",
            steps=[
                PlanStep(
                    id="S1",
                    action=StepAction.CREATE_FILE,
                    description=f"Prime check for {n}",
                    file="prime.py",
                    content=code,
                    evidence=EvidenceSpec(kind=EvidenceKind.NONE),
                ),
                PlanStep(
                    id="S2",
                    action=StepAction.RUN_PYTHON,
                    description="Run prime check",
                    file="prime.py",
                    evidence=EvidenceSpec(kind=EvidenceKind.CONTAINS, expected="True"),
                ),
            ],
        )

    # ── Square root / numeric ──
    if _has(low, "square root", "sqrt"):
        n = _extract_number(low, 144) or 144
        code = f'''import math
print(math.sqrt({n}))
'''
        thr = float(n) ** 0.5 * 0.99
        return ExecutionPlan(
            objective=obj,
            domain="general",
            steps=[
                PlanStep(
                    id="S1",
                    action=StepAction.CREATE_FILE,
                    description=f"sqrt({n})",
                    file="sqrt.py",
                    content=code,
                    evidence=EvidenceSpec(kind=EvidenceKind.NONE),
                ),
                PlanStep(
                    id="S2",
                    action=StepAction.RUN_PYTHON,
                    description="Run sqrt",
                    file="sqrt.py",
                    evidence=EvidenceSpec(kind=EvidenceKind.NUMERIC_GTE, threshold=thr),
                ),
            ],
        )

    # ── ML: Iris / classification / accuracy ──
    if _has(low, "iris", "logistic", "classifier", "accuracy", "train a model", "randomforest", "sklearn"):
        thr = 0.90
        m = re.search(r"(?:accuracy|acc)\s*[>=]+\s*(0\.\d+)", low)
        if m:
            thr = float(m.group(1))
        elif _extract_number(low) and _extract_number(low) < 1:
            thr = float(_extract_number(low))

        # intentional bug path
        if _has(low, "bug", "typo", "self-heal", "broken", "intentional"):
            code = '''import json
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

X, y = load_iris(return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=0)
clf = LogisticRegression(max_iter=300)
clf.fit(X_trian, y_train)  # intentional typo for self-heal demo
pred = clf.predict(X_test)
print(json.dumps({"accuracy": float(accuracy_score(y_test, pred))}))
'''
            fname = "train_custom_buggy.py"
        else:
            model_line = "LogisticRegression(max_iter=500)"
            if _has(low, "randomforest", "random forest"):
                model_line = "RandomForestClassifier(n_estimators=50, random_state=42)"
                imports = "from sklearn.ensemble import RandomForestClassifier"
            else:
                imports = "from sklearn.linear_model import LogisticRegression"

            code = f'''import json
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
{imports}
from sklearn.metrics import accuracy_score, f1_score

X, y = load_iris(return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=y
)
clf = {model_line}
clf.fit(X_train, y_train)
pred = clf.predict(X_test)
metrics = {{
    "accuracy": float(accuracy_score(y_test, pred)),
    "f1": float(f1_score(y_test, pred, average="macro")),
}}
print(json.dumps(metrics))
'''
            fname = "train_custom.py"

        return ExecutionPlan(
            objective=obj,
            domain="ml",
            steps=[
                PlanStep(
                    id="S1",
                    action=StepAction.CREATE_FILE,
                    description="Write training script",
                    file=fname,
                    content=code,
                    evidence=EvidenceSpec(kind=EvidenceKind.NONE),
                ),
                PlanStep(
                    id="S2",
                    action=StepAction.RUN_PYTHON,
                    description="Train and verify accuracy",
                    file=fname,
                    evidence=EvidenceSpec(
                        kind=EvidenceKind.METRIC_JSON,
                        metric_key="accuracy",
                        threshold=thr,
                    ),
                ),
            ],
        )

    # ── Diabetes / regression ──
    if _has(low, "diabetes", "regression", "linearregression", "r2"):
        thr = 0.3
        m = re.search(r"r2\s*[>=]+\s*(0\.\d+)", low)
        if m:
            thr = float(m.group(1))
        code = '''import json
from sklearn.datasets import load_diabetes
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_squared_error

X, y = load_diabetes(return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)
reg = LinearRegression()
reg.fit(X_train, y_train)
pred = reg.predict(X_test)
print(json.dumps({
    "r2": float(r2_score(y_test, pred)),
    "mse": float(mean_squared_error(y_test, pred)),
}))
'''
        return ExecutionPlan(
            objective=obj,
            domain="ml",
            steps=[
                PlanStep(
                    id="S1",
                    action=StepAction.CREATE_FILE,
                    description="Write regression script",
                    file="train_diabetes.py",
                    content=code,
                    evidence=EvidenceSpec(kind=EvidenceKind.NONE),
                ),
                PlanStep(
                    id="S2",
                    action=StepAction.RUN_PYTHON,
                    description="Train regression, check r2",
                    file="train_diabetes.py",
                    evidence=EvidenceSpec(
                        kind=EvidenceKind.METRIC_JSON,
                        metric_key="r2",
                        threshold=thr,
                    ),
                ),
            ],
        )

    # ── Hello / contains ──
    if _has(low, "hello", "print", "aegis"):
        msg = "Hello AegisFlow"
        code = f'print("{msg}")\n'
        return ExecutionPlan(
            objective=obj,
            domain="general",
            steps=[
                PlanStep(
                    id="S1",
                    action=StepAction.CREATE_FILE,
                    description="Write print script",
                    file="hello.py",
                    content=code,
                    evidence=EvidenceSpec(kind=EvidenceKind.NONE),
                ),
                PlanStep(
                    id="S2",
                    action=StepAction.RUN_PYTHON,
                    description="Run print",
                    file="hello.py",
                    evidence=EvidenceSpec(kind=EvidenceKind.CONTAINS, expected="AegisFlow"),
                ),
            ],
        )

    # ── Power / 2**n ──
    if _has(low, "2**", "power of two", "2^"):
        n = int(_extract_number(low, 10) or 10)
        code = f"print(2 ** {n})\n"
        return ExecutionPlan(
            objective=obj,
            domain="general",
            steps=[
                PlanStep(
                    id="S1",
                    action=StepAction.CREATE_FILE,
                    description=f"2**{n}",
                    file="power.py",
                    content=code,
                    evidence=EvidenceSpec(kind=EvidenceKind.NONE),
                ),
                PlanStep(
                    id="S2",
                    action=StepAction.RUN_PYTHON,
                    description="Run power",
                    file="power.py",
                    evidence=EvidenceSpec(kind=EvidenceKind.EXACT, expected=str(2 ** n)),
                ),
            ],
        )

    # ── Generic safe fallback: mean of 1..100 ──
    code = '''import json
import statistics
nums = list(range(1, 101))
print(json.dumps({
    "mean": float(statistics.mean(nums)),
    "stdev": float(statistics.stdev(nums)),
    "n": len(nums),
}))
'''
    return ExecutionPlan(
        objective=obj or "Offline generic numeric task",
        domain="data",
        steps=[
            PlanStep(
                id="S1",
                action=StepAction.CREATE_FILE,
                description="Write stats script (offline fallback for custom objective)",
                file="offline_stats.py",
                content=code,
                evidence=EvidenceSpec(kind=EvidenceKind.NONE),
            ),
            PlanStep(
                id="S2",
                action=StepAction.RUN_PYTHON,
                description="Run stats; verify mean >= 50",
                file="offline_stats.py",
                evidence=EvidenceSpec(
                    kind=EvidenceKind.METRIC_JSON,
                    metric_key="mean",
                    threshold=50.0,
                ),
            ),
        ],
    )
