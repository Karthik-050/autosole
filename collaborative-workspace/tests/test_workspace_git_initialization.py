import tempfile
import unittest
from pathlib import Path

from backend.git.manager import GitManager
from backend.workspace.manager import WorkspaceManager


class TestWorkspaceGitInitialization(unittest.TestCase):
    def test_new_workspace_is_initialized_as_independent_main_repository(self):
        workspace_root = Path(__file__).resolve().parents[1] / "workspace"
        with tempfile.TemporaryDirectory(dir=workspace_root) as temp_dir:
            manager = WorkspaceManager()
            manager.base_dir = Path(temp_dir)
            manager._meta_file = manager.base_dir / ".workspaces_meta.json"
            manager._load_meta()

            workspace_id = manager.create_workspace(name="Git initialization regression")
            status = GitManager(manager._safe_path(workspace_id)).get_status()

            self.assertTrue(status["is_repo"])
            self.assertEqual(status["branch"], "main")
            self.assertEqual(status["commit_count"], 0)
            self.assertEqual(status["untracked"], [])


if __name__ == "__main__":
    unittest.main()
