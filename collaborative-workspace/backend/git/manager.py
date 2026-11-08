import subprocess
import base64
import os
import re
from pathlib import Path
from pathlib import PurePosixPath
from typing import Dict, Any, List, Optional
from urllib.parse import urlsplit

class GitManager:
    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    def _run_git(self, args: List[str], env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        return subprocess.run(
            ["git", *args],
            cwd=str(self.workspace_path),
            capture_output=True,
            text=True,
            env=process_env,
            timeout=300,
        )

    def is_git_repo(self) -> bool:
        if not self.workspace_path.exists():
            return False
        res = self._run_git(["rev-parse", "--show-toplevel"])
        if res.returncode != 0:
            return False

        try:
            git_root = Path(res.stdout.strip()).resolve()
            return git_root == self.workspace_path.resolve()
        except (OSError, RuntimeError):
            return False

    def init_repo(self) -> Dict[str, Any]:
        """Initialize Git in workspace and make initial commit if empty."""
        if not self.workspace_path.exists():
            raise FileNotFoundError("Workspace does not exist")

        if not self.is_git_repo():
            res = self._run_git(["init", "--initial-branch=main"])
            if res.returncode != 0:
                raise RuntimeError(f"Git init failed: {res.stderr}")

        # Configure default local user if not configured
        self._run_git(["config", "user.name", "Collaborative Developer"])
        self._run_git(["config", "user.email", "dev@collaborative-workspace.local"])

        return {
            "success": True,
            "message": "Git repository initialized successfully",
            "branch": self.get_status()["branch"],
        }

    def get_remote_url(self, remote: str = "origin") -> Optional[str]:
        if not self.is_git_repo():
            return None
        result = self._run_git(["remote", "get-url", remote])
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None

    def get_current_branch(self) -> Optional[str]:
        if not self.is_git_repo():
            return None
        result = self._run_git(["branch", "--show-current"])
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None

    def _get_remote_divergence(self, branch: Optional[str], commit_count: int, has_remote: bool) -> tuple[int, int]:
        """Return (ahead, behind) against the configured upstream or origin branch."""
        if not has_remote or not branch:
            return 0, 0

        upstream = self._run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
        upstream_ref = upstream.stdout.strip() if upstream.returncode == 0 else ""
        if not upstream_ref:
            origin_ref = f"refs/remotes/origin/{branch}"
            found = self._run_git(["rev-parse", "--verify", "--quiet", origin_ref])
            if found.returncode == 0:
                upstream_ref = f"origin/{branch}"
            else:
                # A newly created remote branch has no upstream ref yet.
                return commit_count, 0

        counts = self._run_git(["rev-list", "--left-right", "--count", f"{upstream_ref}...HEAD"])
        if counts.returncode != 0:
            return 0, 0
        parts = counts.stdout.split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            return 0, 0
        behind, ahead = (int(part) for part in parts)
        return ahead, behind

    def connect_github_repository(
        self,
        url: str,
        branch: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch a GitHub repository into a newly created empty workspace."""
        parsed = urlsplit(url.strip())
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or len(path_parts) != 2
            or any(part in (".", "..") for part in path_parts)
            or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in path_parts)
        ):
            raise ValueError("Enter a public GitHub repository URL, such as https://github.com/owner/repository")

        if not self.is_git_repo():
            self.init_repo()
        status = self.get_status()
        if status["commit_count"] or not status["clean"]:
            raise ValueError("Pulling a repository requires an empty workspace with no existing commits or local files")

        clone_url = f"https://github.com/{path_parts[0]}/{path_parts[1]}"
        if not clone_url.endswith(".git"):
            clone_url += ".git"

        git_env = {}
        if access_token:
            encoded = base64.b64encode(f"x-access-token:{access_token}".encode()).decode("ascii")
            git_env = {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {encoded}",
            }

        head = self._run_git(["ls-remote", "--symref", clone_url, "HEAD"], env=git_env)
        if head.returncode != 0:
            raise RuntimeError(f"Could not access GitHub repository: {head.stderr.strip() or 'git ls-remote failed'}")
        remote_branch = next(
            (line.split("\t", 1)[0].split("refs/heads/", 1)[1]
             for line in head.stdout.splitlines()
             if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD")),
            None,
        )
        target_branch = (branch or remote_branch or "").strip()
        if not target_branch or target_branch.startswith("-") or ".." in target_branch or "@{" in target_branch:
            raise ValueError("Could not determine a valid default branch; enter a branch name")
        ref_check = self._run_git(["check-ref-format", "--branch", target_branch])
        if ref_check.returncode != 0:
            raise ValueError("Enter a valid Git branch name")

        remote = self._run_git(["remote", "add", "origin", clone_url])
        if remote.returncode != 0:
            raise RuntimeError(f"Could not configure GitHub remote: {remote.stderr.strip()}")
        fetch = self._run_git(["fetch", "--depth=1", "origin", target_branch], env=git_env)
        if fetch.returncode != 0:
            self._run_git(["remote", "remove", "origin"])
            raise RuntimeError(f"Could not fetch branch '{target_branch}': {fetch.stderr.strip()}")
        checkout = self._run_git(["checkout", "--force", "-B", target_branch, "FETCH_HEAD"])
        if checkout.returncode != 0:
            self._run_git(["remote", "remove", "origin"])
            raise RuntimeError(f"Could not check out branch '{target_branch}': {checkout.stderr.strip()}")
        self._run_git(["branch", "--set-upstream-to", f"origin/{target_branch}", target_branch])
        return {"success": True, "remote": clone_url, "branch": target_branch}

    def get_status(self) -> Dict[str, Any]:
        """Get branch name, modified, untracked, and staged files."""
        if not self.is_git_repo():
            return {
                "is_repo": False,
                "branch": None,
                "clean": True,
                "staged": [],
                "unstaged": [],
                "untracked": [],
                "commit_count": 0,
                "has_remote": False,
                "ahead": 0,
                "behind": 0,
            }

        # Branch
        branch_res = self._run_git(["branch", "--show-current"])
        branch = branch_res.stdout.strip()
        if not branch:
            # Maybe HEAD detached or unborn branch
            head_res = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
            branch = head_res.stdout.strip() or "main"

        # Status --porcelain
        status_res = self._run_git(["status", "--porcelain"])
        staged = []
        unstaged = []
        untracked = []

        for line in status_res.stdout.splitlines():
            if not line:
                continue
            index_status = line[0]
            worktree_status = line[1]
            file_path = line[3:].strip()

            if index_status == "?" and worktree_status == "?":
                untracked.append(file_path)
            else:
                if index_status not in (" ", "?"):
                    staged.append({"file": file_path, "status": index_status})
                if worktree_status not in (" ", "?"):
                    unstaged.append({"file": file_path, "status": worktree_status})

        # Commit count
        count_res = self._run_git(["rev-list", "--count", "HEAD"])
        commit_count = int(count_res.stdout.strip()) if count_res.returncode == 0 and count_res.stdout.strip().isdigit() else 0
        remote_url = self.get_remote_url()
        ahead, behind = self._get_remote_divergence(branch, commit_count, bool(remote_url))

        return {
            "is_repo": True,
            "branch": branch,
            "clean": len(staged) == 0 and len(unstaged) == 0 and len(untracked) == 0,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "commit_count": commit_count,
            "has_remote": bool(remote_url),
            "ahead": ahead,
            "behind": behind,
        }

    def commit(self, message: str, author: Optional[str] = None) -> Dict[str, Any]:
        """Stages all changes and creates a commit."""
        if not self.is_git_repo():
            self.init_repo()

        # Stage all changes
        add_res = self._run_git(["add", "-A"])
        if add_res.returncode != 0:
            raise RuntimeError(f"Git add failed: {add_res.stderr}")

        # Check if there is anything to commit
        status = self.get_status()
        if status["clean"]:
            return {
                "committed": False,
                "message": "Working tree clean, nothing to commit",
                "commit_hash": None,
            }

        commit_args = ["commit", "-m", message.strip() or "Update project files"]
        if author:
            commit_args.extend(["--author", f"{author} <{author}@workspace.local>"])

        commit_res = self._run_git(commit_args)
        if commit_res.returncode != 0:
            raise RuntimeError(f"Git commit failed: {commit_res.stderr}")

        # Get latest commit hash
        hash_res = self._run_git(["rev-parse", "HEAD"])
        commit_hash = hash_res.stdout.strip()

        return {
            "committed": True,
            "message": "Changes committed successfully",
            "commit_hash": commit_hash,
            "short_hash": commit_hash[:8] if commit_hash else "",
        }

    def push_to_remote(self, access_token: Optional[str] = None) -> Dict[str, Any]:
        """Push committed changes to origin without persisting any supplied token."""
        if not self.is_git_repo():
            raise ValueError("This workspace is not a Git repository")

        remote_url = self.get_remote_url()
        if not remote_url:
            raise ValueError("No origin remote is configured. Connect a GitHub repository first.")

        branch = self.get_current_branch()
        if not branch:
            raise ValueError("Cannot push while the repository is in a detached HEAD state")
        ref_check = self._run_git(["check-ref-format", "--branch", branch])
        if ref_check.returncode != 0:
            raise ValueError("The current branch name is invalid")

        status = self.get_status()
        if status["behind"]:
            raise RuntimeError(
                f"The remote branch has {status['behind']} newer commit(s). Pull or synchronize before pushing."
            )
        if not status["ahead"]:
            return {
                "pushed": False,
                "branch": branch,
                "commit_hash": None,
                "ahead": 0,
                "message": "There are no unpushed commits.",
            }

        git_env = {
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
        }
        if access_token:
            parsed = urlsplit(remote_url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "github.com"
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("A GitHub token can only be used with an HTTPS github.com remote")
            encoded = base64.b64encode(f"x-access-token:{access_token}".encode()).decode("ascii")
            git_env.update({
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {encoded}",
            })

        push_res = self._run_git(["push", "origin", branch], env=git_env)
        if push_res.returncode != 0:
            error = (push_res.stderr or push_res.stdout).strip()
            if access_token:
                error = error.replace(access_token, "[redacted]")
            lowered = error.lower()
            if any(marker in lowered for marker in ("authentication failed", "write access", "403", "could not read username")):
                raise RuntimeError(
                    "GitHub rejected the push. Use a token with repository Contents read and write permission."
                )
            raise RuntimeError(f"Git push failed: {error or 'Git returned an error without details'}")

        head = self._run_git(["rev-parse", "HEAD"])
        commit_hash = head.stdout.strip() if head.returncode == 0 else None
        # Refresh the tracking ref so the UI immediately reports zero outgoing commits.
        self._run_git(["fetch", "--quiet", "origin", branch], env=git_env)
        return {
            "pushed": True,
            "branch": branch,
            "commit_hash": commit_hash,
            "ahead": 0,
            "message": f"Pushed committed changes to origin/{branch}.",
        }

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get commit log history."""
        if not self.is_git_repo():
            return []

        res = self._run_git([
            "log",
            f"-n{limit}",
            "--pretty=format:%H%x09%an%x09%ad%x09%s",
            "--date=iso",
        ])

        if res.returncode != 0 or not res.stdout.strip():
            return []

        history = []
        for line in res.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 4:
                commit_hash, author, date, message = parts[0], parts[1], parts[2], parts[3]
                history.append({
                    "hash": commit_hash,
                    "short_hash": commit_hash[:8],
                    "author": author,
                    "date": date,
                    "message": message,
                })
        return history

    def get_diff(self, file_path: Optional[str] = None) -> str:
        """Get git diff for working tree or specific file."""
        if not self.is_git_repo():
            return ""

        args = ["--literal-pathspecs", "diff"]
        if file_path:
            normalized_path = file_path.replace("\\", "/")
            path = PurePosixPath(normalized_path)
            if (
                "\x00" in normalized_path
                or path.is_absolute()
                or any(part == ".." for part in path.parts)
                or (path.parts and ":" in path.parts[0])
            ):
                raise ValueError("Diff path must be a relative path inside the workspace")
            # `--` prevents a filename beginning with '-' from becoming a Git option.
            args.extend(["--", normalized_path])

        res = self._run_git(args)
        return res.stdout
