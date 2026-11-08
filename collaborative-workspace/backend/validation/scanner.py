import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List

class CodeValidator:
    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    def scan(self) -> Dict[str, Any]:
        """
        Comprehensive project scan:
        1. Syntax check (AST / JSON)
        2. Naming conventions & Linting
        3. Security vulnerabilities & hardcoded secrets
        4. Automated tests execution
        """
        issues: List[Dict[str, Any]] = []

        if not self.workspace_path.exists():
            return {
                "status": "failed",
                "score": 0,
                "mandatory_checks_passed": False,
                "summary": {"errors": 1, "warnings": 0, "info": 0, "total": 1},
                "issues": [{
                    "id": "WS-001",
                    "file_path": str(self.workspace_path),
                    "line": 1,
                    "col": 1,
                    "rule": "workspace-exists",
                    "category": "syntax",
                    "severity": "error",
                    "message": "Workspace path does not exist",
                    "suggested_fix": "Verify that the workspace ID is valid",
                }],
                "test_results": {"executed": False, "passed": 0, "failed": 0, "total": 0, "details": ""},
            }

        # 1. Scan files
        for file_path in self.workspace_path.rglob("*"):
            if not file_path.is_file():
                continue
            # Skip hidden files and virtual envs
            if any(p.startswith(".") or p in ("venv", "__pycache__", "node_modules") for p in file_path.parts):
                continue

            rel_path = str(file_path.relative_to(self.workspace_path))

            if file_path.suffix.lower() == ".py":
                self._scan_python_file(file_path, rel_path, issues)
            elif file_path.suffix.lower() == ".json":
                self._scan_json_file(file_path, rel_path, issues)

        # 2. Run automated tests if any
        test_results = self._run_automated_tests()
        if test_results["failed"] > 0:
            issues.append({
                "id": "TEST-001",
                "file_path": "tests",
                "line": 1,
                "col": 1,
                "rule": "automated-tests",
                "category": "tests",
                "severity": "error",
                "message": f"{test_results['failed']} test(s) failed out of {test_results['total']}",
                "suggested_fix": "Review failing test tracebacks and fix assertions",
            })

        # Calculate metrics
        errors = sum(1 for i in issues if i["severity"] == "error")
        warnings = sum(1 for i in issues if i["severity"] == "warning")
        info = sum(1 for i in issues if i["severity"] == "info")

        # Mandatory checks fail if any error exists
        mandatory_passed = (errors == 0)

        # Score calculation: 100 - (errors * 25) - (warnings * 10) - (info * 2)
        score = max(0, 100 - (errors * 25) - (warnings * 10) - (info * 2))
        status = "passed" if mandatory_passed and warnings == 0 else ("warning" if mandatory_passed else "failed")

        return {
            "status": status,
            "score": score,
            "mandatory_checks_passed": mandatory_passed,
            "summary": {
                "errors": errors,
                "warnings": warnings,
                "info": info,
                "total": len(issues),
            },
            "issues": issues,
            "test_results": test_results,
        }

    def _scan_python_file(self, file_path: Path, rel_path: str, issues: List[Dict[str, Any]]):
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            issues.append({
                "id": "IO-001",
                "file_path": rel_path,
                "line": 1,
                "col": 1,
                "rule": "file-readable",
                "category": "syntax",
                "severity": "error",
                "message": f"Unable to read file: {e}",
                "suggested_fix": "Check file encoding and permissions",
            })
            return

        lines = content.splitlines()

        # Step A: Python AST Syntax check
        try:
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError as e:
            line_no = e.lineno or 1
            col_no = e.offset or 1
            snippet = lines[line_no - 1] if line_no <= len(lines) else ""
            suggested_fix = "Check for matching quotes, parentheses, brackets, or missing colons."
            if "expected ':'" in str(e).lower():
                suggested_fix = "Add a colon ':' at the end of the statement line."
            elif "unexpected indent" in str(e).lower() or "unindent" in str(e).lower():
                suggested_fix = "Normalize indentation (use consistent 4 spaces)."

            issues.append({
                "id": "SYN-PY-001",
                "file_path": rel_path,
                "line": line_no,
                "col": col_no,
                "rule": "syntax-error",
                "category": "syntax",
                "severity": "error",
                "message": f"Python SyntaxError: {e.msg}",
                "code_snippet": snippet.strip(),
                "suggested_fix": suggested_fix,
            })
            # If syntax error, AST tree walk cannot proceed
            return

        # Step B: AST Naming and Security Analysis
        class CodeAuditor(ast.NodeVisitor):
            def __init__(self, parent):
                self.parent = parent

            def visit_FunctionDef(self, node):
                # Naming check: snake_case for functions
                if not re.match(r"^_{0,2}[a-z][a-z0-9_]*_{0,2}$", node.name):
                    snippet = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                    issues.append({
                        "id": "NAME-001",
                        "file_path": rel_path,
                        "line": node.lineno,
                        "col": node.col_offset + 1,
                        "rule": "pep8-function-naming",
                        "category": "naming",
                        "severity": "warning",
                        "message": f"Function name '{node.name}' should use snake_case naming style",
                        "code_snippet": snippet.strip(),
                        "suggested_fix": f"Rename '{node.name}' to lowercase snake_case",
                    })
                self.generic_visit(node)

            def visit_ClassDef(self, node):
                # Naming check: PascalCase for classes
                if not re.match(r"^[A-Z][a-zA-Z0-9]*$", node.name):
                    snippet = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                    issues.append({
                        "id": "NAME-002",
                        "file_path": rel_path,
                        "line": node.lineno,
                        "col": node.col_offset + 1,
                        "rule": "pep8-class-naming",
                        "category": "naming",
                        "severity": "warning",
                        "message": f"Class name '{node.name}' should use PascalCase / CapWords naming style",
                        "code_snippet": snippet.strip(),
                        "suggested_fix": f"Rename '{node.name}' to PascalCase",
                    })
                self.generic_visit(node)

            def visit_Call(self, node):
                # Security: dangerous functions eval(), exec()
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                if func_name in ("eval", "exec"):
                    snippet = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                    issues.append({
                        "id": "SEC-001",
                        "file_path": rel_path,
                        "line": node.lineno,
                        "col": node.col_offset + 1,
                        "rule": "dangerous-eval-exec",
                        "category": "security",
                        "severity": "error",
                        "message": f"Use of dangerous built-in '{func_name}()' exposes arbitrary code execution risk",
                        "code_snippet": snippet.strip(),
                        "suggested_fix": "Refactor to use ast.literal_eval() or safe parsing logic",
                    })

                # Security: os.system or subprocess shell=True
                if func_name == "system":
                    snippet = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                    issues.append({
                        "id": "SEC-002",
                        "file_path": rel_path,
                        "line": node.lineno,
                        "col": node.col_offset + 1,
                        "rule": "dangerous-os-system",
                        "category": "security",
                        "severity": "error",
                        "message": "Use of 'os.system()' can lead to command injection",
                        "code_snippet": snippet.strip(),
                        "suggested_fix": "Use subprocess.run() with a parameterized argument list",
                    })

                self.generic_visit(node)

            def visit_ImportFrom(self, node):
                mod_name = node.module or ""
                if any(alias.name == "*" for alias in node.names):
                    snippet = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                    issues.append({
                        "id": "LINT-001",
                        "file_path": rel_path,
                        "line": node.lineno,
                        "col": node.col_offset + 1,
                        "rule": "no-wildcard-imports",
                        "category": "lint",
                        "severity": "warning",
                        "message": f"Wildcard import 'from {mod_name} import *' pollutes namespace",
                        "code_snippet": snippet.strip(),
                        "suggested_fix": "Explicitly specify the required imported symbols",
                    })
                self.generic_visit(node)

        auditor = CodeAuditor(self)
        auditor.visit(tree)

        # Step C: Regex Secret & Vulnerability Scan across text lines
        secret_patterns = [
            (r"(?i)(api[_-]?key|secret|token|password|passwd)\s*=\s*['\"][a-zA-Z0-9_\-\.]{12,}['\"]", "SEC-003", "Possible hardcoded secret/API key/token detected", "Move secrets into environment variables or secrets manager"),
            (r"ghp_[a-zA-Z0-9]{20,}", "SEC-004", "GitHub Personal Access Token detected", "Revoke token and use environment variables"),
            (r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----", "SEC-005", "Embedded private key detected in source code", "Remove private keys from repository"),
        ]

        for idx, line in enumerate(lines, start=1):
            for pattern, rule_id, msg, fix in secret_patterns:
                if re.search(pattern, line):
                    issues.append({
                        "id": rule_id,
                        "file_path": rel_path,
                        "line": idx,
                        "col": 1,
                        "rule": "hardcoded-secret",
                        "category": "security",
                        "severity": "error",
                        "message": msg,
                        "code_snippet": re.sub(r"=['\"][^'\"]+['\"]", "='***MASKED***'", line).strip(),
                        "suggested_fix": fix,
                    })

    def _scan_json_file(self, file_path: Path, rel_path: str, issues: List[Dict[str, Any]]):
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            json.loads(content)
        except json.JSONDecodeError as e:
            issues.append({
                "id": "SYN-JSON-001",
                "file_path": rel_path,
                "line": e.lineno,
                "col": e.colno,
                "rule": "json-syntax",
                "category": "syntax",
                "severity": "error",
                "message": f"Invalid JSON syntax: {e.msg}",
                "suggested_fix": "Correct malformed JSON commas, quotes, or brackets",
            })

    def _run_automated_tests(self) -> Dict[str, Any]:
        """Discovers and runs test_*.py or *_test.py in workspace."""
        test_files = list(self.workspace_path.rglob("test_*.py")) + list(self.workspace_path.rglob("*_test.py"))
        # Exclude venv
        test_files = [f for f in test_files if "venv" not in f.parts and "__pycache__" not in f.parts]

        if not test_files:
            return {"executed": False, "total": 0, "passed": 0, "failed": 0, "details": "No test files detected"}

        total = 0
        passed = 0
        failed = 0
        output_logs = []

        for tf in test_files:
            total += 1
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "unittest", str(tf.name)],
                    cwd=str(tf.parent),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if proc.returncode == 0:
                    passed += 1
                    output_logs.append(f"PASS: {tf.name}")
                else:
                    failed += 1
                    err_msg = proc.stderr.strip() or proc.stdout.strip()
                    output_logs.append(f"FAIL: {tf.name}\n{err_msg[:300]}")
            except subprocess.TimeoutExpired:
                failed += 1
                output_logs.append(f"TIMEOUT: {tf.name} (exceeded 10s)")
            except Exception as e:
                failed += 1
                output_logs.append(f"ERROR: {tf.name} ({e})")

        return {
            "executed": True,
            "total": total,
            "passed": passed,
            "failed": failed,
            "details": "\n".join(output_logs),
        }
