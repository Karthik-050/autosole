import os
import stat
import unittest

from backend.workspace.manager import WorkspaceManager


class TestWorkspaceDelete(unittest.TestCase):
    def test_delete_handles_readonly_git_object_files(self):
        manager = WorkspaceManager()
        workspace_id = manager.create_workspace(name="Readonly cleanup regression")
        workspace_path = manager._safe_path(workspace_id)
        object_file = workspace_path / ".git" / "objects" / "aa" / "readonly-object"
        object_file.parent.mkdir(parents=True)
        object_file.write_text("test object", encoding="utf-8")
        os.chmod(object_file, stat.S_IREAD)

        manager.delete_workspace(workspace_id)

        self.assertFalse(workspace_path.exists())
        self.assertNotIn(workspace_id, manager.list_workspaces())


if __name__ == "__main__":
    unittest.main()
