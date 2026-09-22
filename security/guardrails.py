"""
AST-based static security guardrails.
Blocks dangerous patterns before any code reaches the sandbox.
More robust than simple string matching.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List, Set, Tuple


# Default forbidden names / attributes
FORBIDDEN_CALLS: Set[str] = {
    "eval", "exec", "compile", "__import__",
    "os.system", "os.popen", "os.remove", "os.rmdir", "os.removedirs",
    "subprocess.run", "subprocess.call", "subprocess.Popen", "subprocess.check_output",
    "shutil.rmtree", "shutil.move",
    "ctypes", "socket", "pty", "commands",
}

FORBIDDEN_IMPORTS: Set[str] = {
    "subprocess", "ctypes", "socket", "pty", "multiprocessing",
    "commands", "pipes",
}

# Allowlisted safe modules for ML / data work
SAFE_IMPORTS: Set[str] = {
    "math", "statistics", "random", "json", "csv", "re", "collections",
    "itertools", "functools", "typing", "dataclasses", "pathlib",
    "numpy", "np", "pandas", "pd", "sklearn", "joblib",
    "matplotlib", "seaborn", "scipy",
}


@dataclass
class GuardrailFinding:
    severity: str  # "block" | "warn"
    message: str
    line: int = 0


@dataclass
class GuardrailReport:
    safe: bool
    findings: List[GuardrailFinding]

    @property
    def block_reasons(self) -> List[str]:
        return [f.message for f in self.findings if f.severity == "block"]


class _DangerVisitor(ast.NodeVisitor):
    def __init__(self, extra_block: List[str] | None = None):
        self.findings: List[GuardrailFinding] = []
        self.extra = set(extra_block or [])

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            name = alias.name.split(".")[0]
            if name in FORBIDDEN_IMPORTS or name in self.extra:
                self.findings.append(GuardrailFinding(
                    "block", f"Forbidden import: {alias.name}", node.lineno
                ))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = (node.module or "").split(".")[0]
        if mod in FORBIDDEN_IMPORTS or mod in self.extra:
            self.findings.append(GuardrailFinding(
                "block", f"Forbidden import from: {node.module}", node.lineno
            ))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        name = self._call_name(node)
        if name:
            if name in FORBIDDEN_CALLS or name in self.extra:
                self.findings.append(GuardrailFinding(
                    "block", f"Forbidden call: {name}()", node.lineno
                ))
            # bare dangerous builtins
            bare = name.split(".")[-1]
            if bare in {"eval", "exec", "compile"} and name in FORBIDDEN_CALLS | {bare}:
                self.findings.append(GuardrailFinding(
                    "block", f"Forbidden builtin: {bare}()", node.lineno
                ))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # os.system style
        full = self._attr_chain(node)
        if full in FORBIDDEN_CALLS or full in self.extra:
            self.findings.append(GuardrailFinding(
                "block", f"Forbidden attribute access: {full}", node.lineno
            ))
        self.generic_visit(node)

    def _call_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return self._attr_chain(node.func)
        return ""

    def _attr_chain(self, node: ast.AST) -> str:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        parts.reverse()
        return ".".join(parts)


def analyze_code(source: str, extra_blocklist: List[str] | None = None) -> GuardrailReport:
    """
    Statically analyze Python source. Returns GuardrailReport.
    safe=False means the payload must not be executed.
    """
    findings: List[GuardrailFinding] = []

    # Quick string heuristics for obfuscation attempts
    lower = source.lower()
    for pattern in ("__import__", "getattr(", "globals()", "locals()", "breakpoint("):
        if pattern in lower:
            findings.append(GuardrailFinding("block", f"Suspicious pattern detected: {pattern}"))

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        findings.append(GuardrailFinding("block", f"Syntax error (cannot analyze): {e}"))
        return GuardrailReport(safe=False, findings=findings)

    visitor = _DangerVisitor(extra_blocklist)
    visitor.visit(tree)
    findings.extend(visitor.findings)

    blocks = [f for f in findings if f.severity == "block"]
    return GuardrailReport(safe=len(blocks) == 0, findings=findings)


def analyze_command(command: str, extra_blocklist: List[str] | None = None) -> GuardrailReport:
    """Lightweight check on shell commands."""
    findings: List[GuardrailFinding] = []
    blocked_tokens = {
        "rm -rf", "mkfs", "dd if=", ":(){", "shutdown", "reboot",
        "curl ", "wget ", "nc ", "ncat ", "chmod 777",
    }
    extra = set(extra_blocklist or [])
    cl = command.lower()
    for tok in blocked_tokens | extra:
        if tok.lower() in cl:
            findings.append(GuardrailFinding("block", f"Forbidden command pattern: {tok}"))
    return GuardrailReport(safe=len(findings) == 0, findings=findings)
