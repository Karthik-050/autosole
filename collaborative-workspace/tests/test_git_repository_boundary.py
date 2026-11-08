import unittest
from pathlib import Path

from backend.git.manager import GitManager


class TestGitRepositoryBoundary(unittest.TestCase):
    def test_parent_repository_is_not_treated_as_workspace_repository(self):
        project_root = Path(__file__).resolve().parents[1]
        workspace_root = project_root / "workspace"

        self.assertTrue(GitManager(project_root).is_git_repo())
        self.assertFalse(GitManager(workspace_root).is_git_repo())


if __name__ == "__main__":
    unittest.main()
