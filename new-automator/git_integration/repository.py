"""
Git repository operations module.

Manages Git repository cloning, fetching, branch checkouts, isolated build
workspaces, commit metadata extraction, and access verification.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import threading
from typing import Generator
import uuid

from .validators import (
    sanitize_repo_name,
    validate_branch_name,
    validate_commit_sha,
    validate_git_url,
)

logger = logging.getLogger(__name__)


# ============================================================
# EXCEPTIONS
# ============================================================

class GitError(Exception):
    """Base exception for Git repository operations."""
    pass


class GitAuthenticationError(GitError):
    """Raised when Git authentication or authorization fails."""
    pass


class GitNetworkError(GitError):
    """Raised when Git encounters a network connectivity or DNS failure."""
    pass


class GitBranchNotFoundError(GitError):
    """Raised when a requested Git branch is not found."""
    pass


class GitCommitNotFoundError(GitError):
    """Raised when a requested Git commit SHA is not found."""
    pass


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass(frozen=True)
class CommitInfo:
    """Metadata for a specific Git commit."""

    sha: str
    short_sha: str
    message: str
    author: str
    timestamp: str


@dataclass(frozen=True)
class CloneResult:
    """Result of creating a build workspace checkout."""

    repo_id: str
    repo_path: Path
    commit: CommitInfo
    branch: str
    is_fresh_clone: bool


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _redact_secrets(text: str, secrets: list[str] | None = None) -> str:
    """Redact tokens, passwords, and sensitive patterns from error messages."""
    if not text:
        return ""

    redacted = text
    if secrets:
        for secret in secrets:
            if secret and len(secret) >= 4:
                redacted = redacted.replace(secret, "[REDACTED]")

    # Redact embedded credentials in URLs: https://user:pass@host
    redacted = re.sub(
        r"https?://([^:@\s]+):([^@\s]+)@",
        r"https://[REDACTED]:[REDACTED]@",
        redacted,
    )

    # Redact common Personal Access Token patterns
    redacted = re.sub(r"ghp_[a-zA-Z0-9]{20,}", "[REDACTED_GH_TOKEN]", redacted)
    redacted = re.sub(r"github_pat_[a-zA-Z0-9_]{20,}", "[REDACTED_GH_PAT]", redacted)
    redacted = re.sub(r"glpat-[a-zA-Z0-9\-]{20,}", "[REDACTED_GL_TOKEN]", redacted)

    return redacted


@contextmanager
def _git_credential_env(credential_token: str | None) -> Generator[dict[str, str], None, None]:
    """Context manager configuring GIT_ASKPASS for secure credential injection."""
    if not credential_token:
        yield {"GIT_TERMINAL_PROMPT": "0"}
        return

    is_windows = os.name == "nt"
    suffix = ".bat" if is_windows else ".sh"
    temp_dir = Path(tempfile.gettempdir())
    script_path = temp_dir / f"automator_askpass_{uuid.uuid4().hex[:8]}{suffix}"

    try:
        if is_windows:
            script_content = (
                "@echo off\r\n"
                "set \"p=%~1\"\r\n"
                "echo %p% | findstr /i \"username\" >nul\r\n"
                "if %errorlevel% equ 0 (\r\n"
                "    echo x-access-token\r\n"
                ") else (\r\n"
                "    echo %AUTOMATOR_GIT_TOKEN%\r\n"
                ")\r\n"
            )
        else:
            script_content = (
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "    *sername*|*Username*) echo \"x-access-token\" ;;\n"
                "    *) echo \"$AUTOMATOR_GIT_TOKEN\" ;;\n"
                "esac\n"
            )

        script_path.write_text(script_content, encoding="utf-8")
        if not is_windows:
            os.chmod(script_path, stat.S_IRWXU)

        env = {
            "GIT_ASKPASS": str(script_path),
            "GIT_TERMINAL_PROMPT": "0",
            "AUTOMATOR_GIT_TOKEN": credential_token,
        }
        yield env
    finally:
        try:
            if script_path.exists():
                script_path.unlink()
        except OSError as exc:
            logger.debug("Failed to remove temporary askpass script %s: %s", script_path, exc)


# ============================================================
# GIT REPOSITORY CLASS
# ============================================================

class GitRepository:
    """Manages Git repository operations with isolated workspaces."""

    def __init__(self, repos_dir: Path, timeout: int = 300) -> None:
        self.repos_dir = Path(repos_dir).resolve()
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def _get_lock(self, repo_id: str) -> threading.Lock:
        with self._global_lock:
            if repo_id not in self._locks:
                self._locks[repo_id] = threading.Lock()
            return self._locks[repo_id]

    def _run_git(
        self,
        args: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess:
        cmd = ["git", *args]
        effective_timeout = timeout if timeout is not None else self.timeout

        merged_env = os.environ.copy()
        merged_env["GIT_TERMINAL_PROMPT"] = "0"
        if env:
            merged_env.update(env)

        secret_token = merged_env.get("AUTOMATOR_GIT_TOKEN")
        secrets = [secret_token] if secret_token else []

        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                env=merged_env,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            safe_cmd = _redact_secrets(" ".join(cmd), secrets)
            raise GitError(f"Git command timed out after {effective_timeout}s: {safe_cmd}") from exc
        except OSError as exc:
            safe_cmd = _redact_secrets(" ".join(cmd), secrets)
            raise GitError(f"Failed to execute git process: {exc}. Command: {safe_cmd}") from exc

        if result.returncode != 0:
            redacted_stderr = _redact_secrets(result.stderr.strip(), secrets)
            safe_cmd = _redact_secrets(" ".join(cmd), secrets)
            lower_err = redacted_stderr.lower()

            if (
                "authentication failed" in lower_err
                or "could not read username" in lower_err
                or ("repository" in lower_err and "not found" in lower_err and secret_token)
            ):
                raise GitAuthenticationError(f"Git authentication failed: {redacted_stderr}")

            if (
                "could not resolve host" in lower_err
                or "failed to connect" in lower_err
                or "connection timed out" in lower_err
            ):
                raise GitNetworkError(f"Git network error: {redacted_stderr}")

            if "pathspec" in lower_err and "did not match any file(s) known to git" in lower_err:
                raise GitBranchNotFoundError(f"Git branch/ref not found: {redacted_stderr}")

            if "reference is not a tree" in lower_err or "not a valid object name" in lower_err:
                raise GitCommitNotFoundError(f"Git commit not found: {redacted_stderr}")

            raise GitError(
                f"Git command failed with exit code {result.returncode}: {safe_cmd}\nStderr: {redacted_stderr}"
            )

        return result

    def generate_repo_id(self, clone_url: str) -> str:
        try:
            parsed = validate_git_url(clone_url)
            slug = sanitize_repo_name(parsed.repo_name)
            hash_input = parsed.clone_url.lower()
        except ValueError:
            raw_name = clone_url.rstrip("/").split("/")[-1].replace(".git", "")
            slug = sanitize_repo_name(raw_name) or "repo"
            hash_input = clone_url.strip().lower()

        hash_suffix = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:12]
        return f"{slug}-{hash_suffix}"

    def get_repo_path(self, repo_id: str) -> Path:
        safe_id = sanitize_repo_name(repo_id) if not re.fullmatch(r"^[a-zA-Z0-9_\-]+$", repo_id) else repo_id
        if ".." in safe_id or "/" in safe_id or "\\" in safe_id:
            raise ValueError(f"Path traversal detected in repo_id: '{repo_id}'")
        repo_path = self.repos_dir / safe_id
        try:
            repo_path.relative_to(self.repos_dir)
        except ValueError:
            raise ValueError(f"Path traversal detected in repo_id: '{repo_id}'")
        return repo_path

    def get_build_workspace(self, repo_id: str, build_id: str) -> Path:
        safe_repo_id = sanitize_repo_name(repo_id) if not re.fullmatch(r"^[a-zA-Z0-9_\-]+$", repo_id) else repo_id
        safe_build_id = sanitize_repo_name(build_id) if not re.fullmatch(r"^[a-zA-Z0-9_\-]+$", build_id) else build_id

        if ".." in safe_repo_id or ".." in safe_build_id or "/" in safe_build_id or "\\" in safe_build_id:
            raise ValueError(
                f"Path traversal detected in workspace path for repo '{repo_id}' and build '{build_id}'"
            )

        workspace_path = self.repos_dir / "workspaces" / safe_repo_id / safe_build_id
        try:
            workspace_path.relative_to(self.repos_dir)
        except ValueError:
            raise ValueError(
                f"Path traversal detected in workspace path for repo '{repo_id}' and build '{build_id}'"
            )
        return workspace_path

    def clone_or_fetch(
        self,
        clone_url: str,
        repo_id: str,
        credential_token: str | None = None,
    ) -> Path:
        with self._get_lock(repo_id):
            repo_path = self.get_repo_path(repo_id)

            with _git_credential_env(credential_token) as auth_env:
                if not repo_path.exists() or not (repo_path / "HEAD").exists():
                    if repo_path.exists():
                        self._remove_directory(repo_path)

                    repo_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        self._run_git(
                            ["clone", "--bare", clone_url, str(repo_path)],
                            env=auth_env,
                        )
                    except Exception:
                        if repo_path.exists():
                            self._remove_directory(repo_path)
                        raise
                else:
                    self._run_git(
                        ["remote", "set-url", "origin", clone_url],
                        cwd=repo_path,
                        env=auth_env,
                    )
                    self._run_git(
                        ["fetch", "--prune", "origin", "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"],
                        cwd=repo_path,
                        env=auth_env,
                    )

            return repo_path

    def checkout_build_workspace(
        self,
        repo_id: str,
        build_id: str,
        branch: str = "main",
        commit_sha: str | None = None,
    ) -> CloneResult:
        clean_branch = validate_branch_name(branch)
        clean_sha = validate_commit_sha(commit_sha) if commit_sha else None

        bare_path = self.get_repo_path(repo_id)
        if not bare_path.exists() or not (bare_path / "HEAD").exists():
            raise GitError(
                f"Bare repository does not exist at '{bare_path}'. Call clone_or_fetch first."
            )

        workspace_path = self.get_build_workspace(repo_id, build_id)
        if workspace_path.exists():
            self.cleanup_workspace(workspace_path)
        workspace_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._run_git(["clone", "--no-hardlinks", str(bare_path), str(workspace_path)])
            self._run_git(["checkout", clean_branch], cwd=workspace_path)

            if clean_sha:
                self._run_git(["checkout", clean_sha], cwd=workspace_path)

            commit_info = self.get_commit_info(workspace_path)

            return CloneResult(
                repo_id=repo_id,
                repo_path=workspace_path,
                commit=commit_info,
                branch=clean_branch,
                is_fresh_clone=True,
            )
        except Exception:
            if workspace_path.exists():
                self.cleanup_workspace(workspace_path)
            raise

    def get_commit_info(self, repo_path: Path) -> CommitInfo:
        res = self._run_git(
            ["log", "-1", "--format=%H%n%h%n%s%n%an%n%aI"],
            cwd=repo_path,
        )
        lines = res.stdout.strip().splitlines()
        if len(lines) < 5:
            raise GitError(f"Failed to parse git log output in {repo_path}: '{res.stdout}'")

        return CommitInfo(
            sha=lines[0].strip(),
            short_sha=lines[1].strip(),
            message=lines[2].strip(),
            author=lines[3].strip(),
            timestamp=lines[4].strip(),
        )

    def get_branches(self, repo_id: str) -> list[str]:
        repo_path = self.get_repo_path(repo_id)
        if not repo_path.exists():
            raise GitError(f"Repository '{repo_id}' not found at {repo_path}")

        res = self._run_git(
            ["for-each-ref", "--format=%(refname:short)", "refs/heads/"],
            cwd=repo_path,
        )
        return [b.strip() for b in res.stdout.splitlines() if b.strip()]

    def get_default_branch(self, repo_id: str) -> str:
        repo_path = self.get_repo_path(repo_id)
        if not repo_path.exists():
            raise GitError(f"Repository '{repo_id}' not found at {repo_path}")

        try:
            res = self._run_git(["symbolic-ref", "--short", "HEAD"], cwd=repo_path)
            branch = res.stdout.strip()
            if branch:
                return branch
        except GitError:
            pass

        branches = self.get_branches(repo_id)
        if "main" in branches:
            return "main"
        if "master" in branches:
            return "master"
        if branches:
            return branches[0]

        return "main"

    def cleanup_workspace(self, workspace_path: Path) -> None:
        path = Path(workspace_path)
        try:
            rel = path.relative_to(self.repos_dir)
            if not rel.parts or len(rel.parts) < 2:
                raise ValueError("Refusing to delete top-level repos directory.")
        except ValueError:
            raise ValueError(
                f"Refusing to delete path outside configured repos directory: {workspace_path}"
            )

        if path.exists():
            self._remove_directory(path)

    def validate_access(
        self,
        clone_url: str,
        credential_token: str | None = None,
    ) -> bool:
        with _git_credential_env(credential_token) as auth_env:
            try:
                self._run_git(["ls-remote", "--heads", clone_url], env=auth_env)
                return True
            except GitError as exc:
                logger.warning("Git access validation failed for '%s': %s", clone_url, exc)
                return False

    @staticmethod
    def _remove_directory(path: Path) -> None:
        def _on_rm_error(func, target_path, exc_info):
            try:
                os.chmod(target_path, stat.S_IWRITE)
                func(target_path)
            except OSError as exc:
                logger.warning("Failed to force delete '%s': %s", target_path, exc)

        shutil.rmtree(path, onerror=_on_rm_error)
