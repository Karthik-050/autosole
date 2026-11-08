import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.git.manager import GitManager


class TestGitDiffPathSafety(unittest.TestCase):
    def setUp(self):
        self.manager = GitManager(Path.cwd())

    def test_filename_cannot_be_parsed_as_git_option(self):
        completed = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="diff", stderr="")
        with patch.object(self.manager, "is_git_repo", return_value=True), patch.object(
            self.manager, "_run_git", return_value=completed
        ) as run_git:
            self.assertEqual(self.manager.get_diff("--output=outside.txt"), "diff")

        run_git.assert_called_once_with(
            ["--literal-pathspecs", "diff", "--", "--output=outside.txt"]
        )

    def test_rejects_paths_outside_workspace(self):
        with patch.object(self.manager, "is_git_repo", return_value=True), patch.object(
            self.manager, "_run_git"
        ) as run_git:
            with self.assertRaises(ValueError):
                self.manager.get_diff(r"nested\..\outside.py")

        run_git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
