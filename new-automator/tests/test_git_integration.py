"""Automated tests for Git repository validation, isolated checkouts, and operations."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

from git_integration.repository import (
    CommitInfo,
    GitAuthenticationError,
    GitBranchNotFoundError,
    GitCommitNotFoundError,
    GitError,
    GitNetworkError,
    GitRepository,
)
from git_integration.validators import (
    sanitize_repo_name,
    validate_branch_name,
    validate_commit_sha,
    validate_git_url,
)


class TestGitValidators(unittest.TestCase):
    """Test URL and Git ref validation logic."""

    def test_valid_https_urls(self):
        parsed = validate_git_url("https://github.com/octocat/Hello-World.git")
        self.assertEqual(parsed.provider, "github.com")
        self.assertEqual(parsed.owner, "octocat")
        self.assertEqual(parsed.repo_name, "Hello-World")
        self.assertEqual(parsed.clone_url, "https://github.com/octocat/Hello-World.git")

    def test_url_without_scheme(self):
        parsed = validate_git_url("github.com/user/my-repo")
        self.assertEqual(parsed.provider, "github.com")
        self.assertEqual(parsed.owner, "user")
        self.assertEqual(parsed.repo_name, "my-repo")

    def test_reject_ssh_urls(self):
        with self.assertRaises(ValueError):
            validate_git_url("git@github.com:user/repo.git")

        with self.assertRaises(ValueError):
            validate_git_url("ssh://git@github.com/user/repo.git")

    def test_reject_empty_and_malformed_urls(self):
        with self.assertRaises(ValueError):
            validate_git_url("")
        with self.assertRaises(ValueError):
            validate_git_url("https://github.com")
        with self.assertRaises(ValueError):
            validate_git_url("ftp://github.com/user/repo")

    def test_allowed_providers_filter(self):
        validate_git_url("https://github.com/user/repo", allowed_providers=["github.com", "gitlab.com"])
        with self.assertRaises(ValueError):
            validate_git_url("https://untrusted.com/user/repo", allowed_providers=["github.com"])

    def test_branch_validation(self):
        self.assertEqual(validate_branch_name("main"), "main")
        self.assertEqual(validate_branch_name("feature/login-v2"), "feature/login-v2")
        self.assertEqual(validate_branch_name("release-1.0"), "release-1.0")

        # Invalid branches
        with self.assertRaises(ValueError):
            validate_branch_name("-flag-injection")
        with self.assertRaises(ValueError):
            validate_branch_name("branch/../escape")
        with self.assertRaises(ValueError):
            validate_branch_name("/leading-slash")
        with self.assertRaises(ValueError):
            validate_branch_name("trailing-slash/")
        with self.assertRaises(ValueError):
            validate_branch_name("bad@{reflog}")
        with self.assertRaises(ValueError):
            validate_branch_name("branch with spaces")

    def test_commit_sha_validation(self):
        self.assertEqual(validate_commit_sha("a1b2c3d"), "a1b2c3d")
        self.assertEqual(
            validate_commit_sha("e4d909c290d0fb1ca068ffaddf22cbd0adddef11"),
            "e4d909c290d0fb1ca068ffaddf22cbd0adddef11",
        )
        with self.assertRaises(ValueError):
            validate_commit_sha("not-a-sha-xyz")
        with self.assertRaises(ValueError):
            validate_commit_sha("abc")  # too short (< 4 chars)

    def test_sanitize_repo_name(self):
        self.assertEqual(sanitize_repo_name("My Super_App.1"), "my-super-app-1")
        self.assertEqual(sanitize_repo_name("con"), "repo-con")  # Windows reserved name
        self.assertEqual(sanitize_repo_name("aux"), "repo-aux")
        self.assertEqual(sanitize_repo_name(""), "repo")


class TestGitRepositoryOperations(unittest.TestCase):
    """Test Git operations using real local Git repositories."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.remote_dir = self.temp_dir / "remote_repo"
        self.repos_storage = self.temp_dir / "automator_repos"
        self.git_manager = GitRepository(self.repos_storage)

        # Initialize a real local git repository to act as origin
        self.remote_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=str(self.remote_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(self.remote_dir), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(self.remote_dir), check=True)

        # Initial commit
        (self.remote_dir / "README.md").write_text("Automator Test", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.remote_dir), check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(self.remote_dir), check=True)

        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.remote_dir), capture_output=True, text=True)
        self.initial_sha = res.stdout.strip()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_clone_and_checkout_workspace(self):
        repo_id = "test-repo-123"
        clone_url = str(self.remote_dir.resolve().as_uri())

        # Clone or fetch bare repo
        bare_path = self.git_manager.clone_or_fetch(clone_url, repo_id)
        self.assertTrue(bare_path.exists())
        self.assertTrue((bare_path / "HEAD").exists())

        # Checkout isolated workspace
        result = self.git_manager.checkout_build_workspace(repo_id, "build-1", branch="main")
        self.assertTrue(result.repo_path.exists())
        self.assertTrue((result.repo_path / "README.md").exists())
        self.assertEqual(result.commit.sha, self.initial_sha)
        self.assertEqual(result.commit.message, "Initial commit")

        # Cleanup workspace
        self.git_manager.cleanup_workspace(result.repo_path)
        self.assertFalse(result.repo_path.exists())

    def test_fetch_subsequent_commit(self):
        repo_id = "test-fetch-repo"
        clone_url = str(self.remote_dir.resolve().as_uri())

        self.git_manager.clone_or_fetch(clone_url, repo_id)

        # Make a second commit in the remote
        (self.remote_dir / "feature.py").write_text("print('feature')", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.remote_dir), check=True)
        subprocess.run(["git", "commit", "-m", "Second commit"], cwd=str(self.remote_dir), check=True)

        # Fetch updates
        self.git_manager.clone_or_fetch(clone_url, repo_id)

        # Checkout build 2
        result = self.git_manager.checkout_build_workspace(repo_id, "build-2", branch="main")
        self.assertTrue((result.repo_path / "feature.py").exists())
        self.assertEqual(result.commit.message, "Second commit")

    def test_checkout_specific_sha(self):
        repo_id = "test-sha-repo"
        clone_url = str(self.remote_dir.resolve().as_uri())
        self.git_manager.clone_or_fetch(clone_url, repo_id)

        # Make a second commit
        (self.remote_dir / "new.txt").write_text("new", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.remote_dir), check=True)
        subprocess.run(["git", "commit", "-m", "Commit 2"], cwd=str(self.remote_dir), check=True)
        self.git_manager.clone_or_fetch(clone_url, repo_id)

        # Checkout exact initial SHA
        result = self.git_manager.checkout_build_workspace(
            repo_id, "build-pinned", branch="main", commit_sha=self.initial_sha
        )
        self.assertEqual(result.commit.sha, self.initial_sha)
        self.assertFalse((result.repo_path / "new.txt").exists())

    def test_missing_branch_error(self):
        repo_id = "test-missing-branch"
        clone_url = str(self.remote_dir.resolve().as_uri())
        self.git_manager.clone_or_fetch(clone_url, repo_id)

        with self.assertRaises(GitError):
            self.git_manager.checkout_build_workspace(repo_id, "build-fail", branch="non-existent-branch")

    def test_concurrent_workspaces_isolation(self):
        repo_id = "test-concurrent"
        clone_url = str(self.remote_dir.resolve().as_uri())
        self.git_manager.clone_or_fetch(clone_url, repo_id)

        results = []
        errors = []

        def worker(build_id):
            try:
                res = self.git_manager.checkout_build_workspace(repo_id, build_id, branch="main")
                results.append(res)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"concurrent-build-{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 4)
        # All workspace directories must be unique
        workspace_paths = {r.repo_path for r in results}
        self.assertEqual(len(workspace_paths), 4)


if __name__ == "__main__":
    unittest.main()
