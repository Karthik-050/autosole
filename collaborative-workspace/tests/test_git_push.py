import base64
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.git.manager import GitManager


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr=stderr)


class TestGitPush(unittest.TestCase):
    def setUp(self):
        self.git = GitManager(Path.cwd())

    def test_remote_divergence_reports_ahead_and_behind(self):
        with patch.object(self.git, "_run_git", side_effect=[completed("origin/main\n"), completed("1\t2\n")]):
            ahead, behind = self.git._get_remote_divergence("main", 5, True)

        self.assertEqual((ahead, behind), (2, 1))

    def test_push_uses_token_in_transient_git_header(self):
        token = "test-github-token"
        with (
            patch.object(self.git, "is_git_repo", return_value=True),
            patch.object(self.git, "get_remote_url", return_value="https://github.com/example/project.git"),
            patch.object(self.git, "get_current_branch", return_value="main"),
            patch.object(self.git, "get_status", return_value={"ahead": 2, "behind": 0}),
            patch.object(
                self.git,
                "_run_git",
                side_effect=[completed(), completed(), completed("abc123\n"), completed()],
            ) as run_git,
        ):
            result = self.git.push_to_remote(access_token=token)

        self.assertTrue(result["pushed"])
        self.assertEqual(result["branch"], "main")
        self.assertEqual(result["commit_hash"], "abc123")
        push_call = run_git.call_args_list[1]
        self.assertEqual(push_call.args[0], ["push", "origin", "main"])
        encoded_header = push_call.kwargs["env"]["GIT_CONFIG_VALUE_0"].split()[-1]
        self.assertEqual(base64.b64decode(encoded_header).decode(), f"x-access-token:{token}")
        self.assertNotIn(token, repr(run_git.call_args_list))

    def test_token_is_not_sent_to_non_github_remote(self):
        with (
            patch.object(self.git, "is_git_repo", return_value=True),
            patch.object(self.git, "get_remote_url", return_value="https://git.example.com/project.git"),
            patch.object(self.git, "get_current_branch", return_value="main"),
            patch.object(self.git, "get_status", return_value={"ahead": 1, "behind": 0}),
            patch.object(self.git, "_run_git", return_value=completed()) as run_git,
        ):
            with self.assertRaisesRegex(ValueError, "only be used with an HTTPS github.com remote"):
                self.git.push_to_remote(access_token="test-token")

        self.assertEqual(run_git.call_args.args[0], ["check-ref-format", "--branch", "main"])

    def test_refuses_push_when_remote_is_ahead(self):
        with (
            patch.object(self.git, "is_git_repo", return_value=True),
            patch.object(self.git, "get_remote_url", return_value="https://github.com/example/project.git"),
            patch.object(self.git, "get_current_branch", return_value="main"),
            patch.object(self.git, "get_status", return_value={"ahead": 2, "behind": 1}),
            patch.object(self.git, "_run_git", return_value=completed()) as run_git,
        ):
            with self.assertRaisesRegex(RuntimeError, "Pull or synchronize"):
                self.git.push_to_remote()

        self.assertEqual(run_git.call_args.args[0], ["check-ref-format", "--branch", "main"])


if __name__ == "__main__":
    unittest.main()
