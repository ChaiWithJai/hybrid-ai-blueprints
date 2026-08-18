"""Prototype AST validation and resource-limited child-process execution.

This is defense in depth for generated calculation scripts. It is not a
hardened multi-tenant boundary, VM, container, chroot, or network namespace.
On macOS, the child also runs under a sandbox-exec profile that denies network
access and process forks and limits file writes to its temporary run directory.
"""

from __future__ import annotations

import ast
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional, Set, Tuple


class ASTSecurityAuditor(ast.NodeVisitor):
    """Reject syntax outside the deliberately small calculation language."""

    DEFAULT_ALLOWED_IMPORTS = {"math", "json", "re"}
    BANNED_FUNCTIONS = {
        "eval", "exec", "__import__", "open", "compile", "input", "breakpoint",
        "globals", "locals", "vars", "getattr", "setattr", "delattr", "help",
        "dir", "memoryview",
    }

    def __init__(self, allowed_imports: Optional[Set[str]] = None):
        self.allowed_imports = set(
            self.DEFAULT_ALLOWED_IMPORTS if allowed_imports is None else allowed_imports
        )
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            base = alias.name.split(".")[0]
            if base not in self.allowed_imports:
                self.violations.append(f"Import not allowlisted: '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        base = (node.module or "").split(".")[0]
        if node.level or base not in self.allowed_imports:
            self.violations.append(f"Import not allowlisted: '{node.module or '[relative]'}'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in self.BANNED_FUNCTIONS:
            self.violations.append(f"Disallowed function call: '{node.func.id}()'")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if node.id.startswith("__") and node.id != "__name__":
            self.violations.append(f"Disallowed internal name: '{node.id}'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr.startswith("_"):
            self.violations.append(f"Disallowed private/internal attribute: '{node.attr}'")
        self.generic_visit(node)


class SubprocessSandbox:
    """Run AST-approved code in an isolated-mode Python child process."""

    def __init__(
        self,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = 1024 * 1024,
        max_file_bytes: int = 1024 * 1024,
        protected_read_roots: Optional[list[str]] = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.max_file_bytes = max_file_bytes
        requested_roots = ["/Users", "/Volumes", "/Network", os.getcwd()]
        if protected_read_roots:
            requested_roots.extend(protected_read_roots)
        self.protected_read_roots: list[str] = []
        for requested in requested_roots:
            resolved = os.path.realpath(requested)
            if resolved == "/":
                continue
            if any(
                os.path.commonpath((resolved, parent)) == parent
                for parent in self.protected_read_roots
            ):
                continue
            self.protected_read_roots.append(resolved)

    @staticmethod
    def _sandbox_literal(value: str) -> str:
        """Escape one filesystem path for a sandbox profile string literal."""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @classmethod
    def macos_profile(
        cls,
        writable_directory: str,
        protected_read_roots: Optional[list[str]] = None,
    ) -> str:
        """Return the measured macOS profile used for generated code."""
        writable = cls._sandbox_literal(os.path.realpath(writable_directory))
        requested_roots = ["/Users", "/Volumes", "/Network", os.getcwd()]
        if protected_read_roots:
            requested_roots.extend(protected_read_roots)
        read_denials = []
        resolved_roots: list[str] = []
        for requested in requested_roots:
            resolved = os.path.realpath(requested)
            if resolved == "/" or any(
                os.path.commonpath((resolved, parent)) == parent
                for parent in resolved_roots
            ):
                continue
            resolved_roots.append(resolved)
            literal = cls._sandbox_literal(resolved)
            read_denials.append(f'(deny file-read* (subpath "{literal}"))\n')
        return (
            "(version 1)\n"
            "(allow default)\n"
            "(deny network*)\n"
            "(deny process-fork)\n"
            + "".join(read_denials)
            + f'(deny file-write* (require-not (subpath "{writable}")))\n'
        )

    def execute_script(
        self,
        code_string: str,
        injected_variables: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        try:
            tree = ast.parse(code_string)
        except SyntaxError as exc:
            return False, f"Syntax Error: {exc}", {}

        auditor = ASTSecurityAuditor()
        auditor.visit(tree)
        if auditor.violations:
            return False, "AST Sandbox Security Violation: " + " | ".join(auditor.violations), {}

        temp_dir = tempfile.mkdtemp(
            prefix="prism-sandbox-",
            dir="/private/tmp" if sys.platform == "darwin" else None,
        )
        try:
            prefix = ""
            if injected_variables:
                context_path = os.path.join(temp_dir, "_context.json")
                with open(context_path, "w", encoding="utf-8") as handle:
                    json.dump(injected_variables, handle)
                prefix = (
                    "import json as _prism_json\n"
                    "with open('_context.json', encoding='utf-8') as _prism_handle:\n"
                    "    ctx = _prism_json.load(_prism_handle)\n"
                )

            script_path = os.path.join(temp_dir, "script.py")
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write(prefix + code_string)

            command = [sys.executable, "-I", "-S", script_path]
            isolation = {
                "mode": "resource_limited_python_child",
                "os_policy_enforced": False,
                "network_access": "not_os_enforced",
                "process_forks": "not_os_enforced",
                "file_writes": "not_os_confined",
            }
            if sys.platform == "darwin":
                sandbox_exec = shutil.which("sandbox-exec", path="/usr/bin:/bin")
                if not sandbox_exec:
                    return False, "Subprocess Error: macOS sandbox-exec is unavailable", {
                        "isolation": {
                            **isolation,
                            "mode": "macos_sandbox_exec_required_but_unavailable",
                        }
                    }
                profile_path = os.path.join(temp_dir, "profile.sb")
                with open(profile_path, "w", encoding="utf-8") as handle:
                    handle.write(self.macos_profile(temp_dir, self.protected_read_roots))
                os.chmod(profile_path, 0o600)
                command = [sandbox_exec, "-f", profile_path, *command]
                isolation = {
                    "mode": "macos_sandbox_exec_profile",
                    "os_policy_enforced": True,
                    "network_access": "denied",
                    "process_forks": "denied",
                    "file_writes": "temporary_run_directory_only",
                    "file_read_denied_roots": self.protected_read_roots,
                }

            def apply_limits():
                cpu_soft = max(1, int(self.timeout_seconds) + 1)
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_soft, cpu_soft + 1))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                resource.setrlimit(resource.RLIMIT_FSIZE, (self.max_file_bytes, self.max_file_bytes))
                resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
                if sys.platform != "darwin":
                    memory_soft = 256 * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (memory_soft, memory_soft * 2))

            env = {
                "PATH": "/usr/bin:/bin",
                "HOME": temp_dir,
                "TMPDIR": temp_dir,
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            output_path = os.path.join(temp_dir, "output.log")
            timed_out = False
            return_code = None
            with open(output_path, "w+", encoding="utf-8", errors="replace") as output:
                try:
                    result = subprocess.run(
                        command,
                        cwd=temp_dir,
                        env=env,
                        preexec_fn=apply_limits,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        timeout=self.timeout_seconds,
                        text=True,
                    )
                    return_code = result.returncode
                except subprocess.TimeoutExpired:
                    timed_out = True
                except Exception as exc:
                    return False, f"Subprocess Error: {exc}", {"isolation": isolation}
                output.flush()
                output.seek(0)
                output_text = output.read(self.max_output_bytes)

            if timed_out:
                return False, f"Execution timed out after {self.timeout_seconds} seconds\n{output_text}".rstrip(), {"isolation": isolation}
            success = return_code == 0
            if not success and not output_text:
                output_text = f"Sandbox process exited with code {return_code}"
            return success, output_text, {"isolation": isolation}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
