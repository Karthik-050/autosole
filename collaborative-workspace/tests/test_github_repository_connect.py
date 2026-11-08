import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.git.manager import GitManager


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr=stderr)


class TestGitHubRepositoryConnect(unittest.TestCase):
    def setUp(self):
        self.git = GitManager(Path.cwd())

    def test_connect_fetches_default_branch_without_persisting_token(self):
        with (
            patch.object(self.git, "is_git_repo", return_value=True),
            patch.object(self.git, "get_status", return_value={"commit_count": 0, "clean": True}),
            patch.object(
                self.git,
                "_run_git",
                side_effect=[
                    completed("ref: refs/heads/trunk\tHEAD\nabc123\tHEAD\n"),
                    completed(),  # branch format
                    completed(),  # remote add
                    completed(),  # fetch
                    completed(),  # checkout
                    completed(),  # upstream
                ],
            ) as run_git,
        ):
            result = self.git.connect_github_repository(
                "https://github.com/example/project", access_token="test-token"
            )

        self.assertEqual(result, {
            "success": True,
            "remote": "https://github.com/example/project.git",
            "branch": "trunk",
        })
        fetch_call = run_git.call_args_list[3]
        self.assertEqual(fetch_call.args[0], ["fetch", "--depth=1", "origin", "trunk"])
        self.assertNotIn("test-token", repr(run_git.call_args_list))
        self.assertIn("test-token", __import__("base64").b64decode(
            fetch_call.kwargs["env"]["GIT_CONFIG_VALUE_0"].split()[-1]
        ).decode())

    def test_rejects_non_github_urls_before_git_commands(self):
        with patch.object(self.git, "_run_git") as run_git:
            with self.assertRaisesRegex(ValueError, "GitHub repository URL"):
                self.git.connect_github_repository("https://example.com/owner/project")
        run_git.assert_not_called()

    def test_refuses_to_overwrite_local_workspace_files(self):
        with (
            patch.object(self.git, "is_git_repo", return_value=True),
            patch.object(self.git, "get_status", return_value={"commit_count": 0, "clean": False}),
            patch.object(self.git, "_run_git") as run_git,
        ):
            with self.assertRaisesRegex(ValueError, "empty workspace"):
                self.git.connect_github_repository("https://github.com/example/project")
        run_git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
