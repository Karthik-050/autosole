import sys
import unittest
import shutil
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings
from backend.workspace.manager import WorkspaceManager
from backend.git.manager import GitManager
from backend.validation.scanner import CodeValidator
from backend.validation.detector import detect_project
from backend.docker.manager import DockerManager
from backend.jenkins.manager import JenkinsManager, generate_pipeline
from backend.deployment.manager import DeploymentManager
from backend.dashboard.manager import DashboardManager
from backend.pipeline.orchestrator import PipelineOrchestrator
import asyncio

class TestBackendIntegration(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_path = Path(self.temp_dir)
        self.ws_manager = WorkspaceManager()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_workspace_crud_and_security(self):
        # 1. Create workspace
        wid = self.ws_manager.create_workspace(name="Unit Test WS", template="python")
        self.assertIsNotNone(wid)

        # 2. List workspaces
        workspaces = self.ws_manager.list_workspaces()
        self.assertIn(wid, workspaces)

        # 3. Read pre-created app.py from template
        content = self.ws_manager.read_file(wid, "app.py")
        self.assertIn("Flask", content)

        # 4. Write new file
        self.ws_manager.write_file(wid, "helper.py", "def add(a, b):\n    return a + b\n")
        files = self.ws_manager.list_files(wid)
        self.assertIn("helper.py", files)

        # 5. Security: Path traversal protection
        with self.assertRaises(PermissionError):
            self.ws_manager.read_file(wid, "../outside.txt")

        with self.assertRaises(PermissionError):
            self.ws_manager.write_file(wid, "../../etc/passwd", "evil")

        # Cleanup
        self.ws_manager.delete_workspace(wid)
        self.assertNotIn(wid, self.ws_manager.list_workspaces())

    def test_git_operations(self):
        test_ws = self.workspace_path / "git_test"
        test_ws.mkdir()
        (test_ws / "code.py").write_text("print('v1')\n")

        git = GitManager(test_ws)
        self.assertFalse(git.is_git_repo())

        # Init
        init_res = git.init_repo()
        self.assertTrue(init_res["success"])
        self.assertTrue(git.is_git_repo())

        # Status before commit
        status = git.get_status()
        self.assertFalse(status["clean"])

        # Commit
        commit_res = git.commit("Initial commit for testing")
        self.assertTrue(commit_res["committed"])
        self.assertIsNotNone(commit_res["commit_hash"])

        # History
        history = git.get_history()
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(history[0]["message"], "Initial commit for testing")

        # Modify file and check diff
        (test_ws / "code.py").write_text("print('v2 modified')\n")
        diff = git.get_diff()
        self.assertIn("+print('v2 modified')", diff)

    def test_code_validation_scanner(self):
        test_ws = self.workspace_path / "val_test"
        test_ws.mkdir()

        # Valid file
        (test_ws / "good.py").write_text("def hello_world():\n    return 'clean code'\n")
        validator = CodeValidator(test_ws)
        res = validator.scan()
        self.assertTrue(res["mandatory_checks_passed"])
        self.assertEqual(res["summary"]["errors"], 0)
        self.assertEqual(res["score"], 100)

        # File with fatal syntax error
        (test_ws / "broken.py").write_text("def bad_function(\n    return 123\n")
        res2 = validator.scan()
        self.assertFalse(res2["mandatory_checks_passed"])
        self.assertGreaterEqual(res2["summary"]["errors"], 1)
        syntax_issues = [i for i in res2["issues"] if i["category"] == "syntax"]
        self.assertGreaterEqual(len(syntax_issues), 1)
        self.assertIn("suggested_fix", syntax_issues[0])

        # File with security vulnerability
        (test_ws / "broken.py").unlink()
        (test_ws / "vulnerable.py").write_text("secret_token = 'ghp_1234567890123456789012345'\neval('2 + 2')\n")
        res3 = validator.scan()
        sec_issues = [i for i in res3["issues"] if i["category"] == "security"]
        self.assertGreaterEqual(len(sec_issues), 2)

    def test_docker_and_jenkins_graceful_status(self):
        dm = DockerManager()
        d_status = dm.get_status()
        self.assertIn("available", d_status)
        self.assertIn("status", d_status)

        jm = JenkinsManager()
        j_status = jm.get_status()
        self.assertIn("available", j_status)
        self.assertIn("status", j_status)

        # Jenkins pipeline generation
        script = generate_pipeline("my-app", "my-app:latest", "app-container", 5001)
        self.assertIn("pipeline {", script)
        self.assertIn("stage('Build Docker Image')", script)

    def test_pipeline_orchestration_and_quality_gate(self):
        # 1. Pipeline stops on validation error
        wid_fail = self.ws_manager.create_workspace(name="Fail WS")
        ws_fail_path = self.ws_manager._safe_path(wid_fail)
        (ws_fail_path / "bad.py").write_text("def broken():\n    return (\n")

        orchestrator = PipelineOrchestrator()
        run = asyncio.run(orchestrator.trigger_pipeline(
            project_id=wid_fail,
            project_path=ws_fail_path,
            auto_commit=True,
            build_docker=False,
            deploy_container=False,
            wait=True,
        ))

        final_run = orchestrator.get_run(run["run_id"])
        self.assertEqual(final_run["status"], "failed")
        self.assertIn("Code validation failed", final_run["error"])

        # Verify downstream stages were skipped
        val_stage = next(s for s in final_run["stages"] if s["name"] == "validation")
        build_stage = next(s for s in final_run["stages"] if s["name"] == "build")
        deploy_stage = next(s for s in final_run["stages"] if s["name"] == "deploy")
        self.assertEqual(val_stage["status"], "failed")
        self.assertEqual(build_stage["status"], "skipped")
        self.assertEqual(deploy_stage["status"], "skipped")

        # 2. Pipeline succeeds on valid project
        wid_ok = self.ws_manager.create_workspace(name="Success WS")
        ws_ok_path = self.ws_manager._safe_path(wid_ok)
        (ws_ok_path / "app.py").write_text("def hello():\n    return 'ok'\n")

        run_ok = asyncio.run(orchestrator.trigger_pipeline(
            project_id=wid_ok,
            project_path=ws_ok_path,
            auto_commit=True,
            build_docker=False,
            deploy_container=False,
            wait=True,
        ))

        final_run_ok = orchestrator.get_run(run_ok["run_id"])
        self.assertEqual(final_run_ok["status"], "success")

        # Cleanup
        self.ws_manager.delete_workspace(wid_fail)
        self.ws_manager.delete_workspace(wid_ok)

    def test_dashboard_manager_real_data(self):
        dash = DashboardManager(
            workspace_mgr=self.ws_manager,
            docker_mgr=DockerManager(),
            jenkins_mgr=JenkinsManager(),
            pipeline_mgr=PipelineOrchestrator(),
            deploy_mgr=DeploymentManager(),
        )
        stats = dash.get_summary()
        self.assertIn("projects", stats)
        self.assertIn("services", stats)
        self.assertIn("active_project_metrics", stats)
        self.assertIn("recent_pipeline_runs", stats)

if __name__ == "__main__":
    unittest.main()
