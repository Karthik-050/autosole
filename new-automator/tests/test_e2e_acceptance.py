"""End-to-End Acceptance Test for Git-Driven CI/CD Workflow.

Validates:
1. Repository connection
2. Initial pipeline build with stack detection & Dockerfile generation
3. Webhook push trigger with exact commit SHA
4. Failing test rejection preserving last healthy preview
5. Corrected commit succeeding and safely replacing candidate
"""

import hashlib
import hmac
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from config import get_settings
import database
from orchestrator import BuildOrchestrator
from server import app


class TestEndToEndAcceptance(unittest.IsolatedAsyncioTestCase):
    """Full lifecycle automated acceptance test suite."""

    async def asyncSetUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.origin_repo = self.temp_dir / "my_project_origin"
        self.origin_repo.mkdir()

        # Database and storage isolation
        self.db_path = self.temp_dir / "e2e.db"
        self.old_db = get_settings().DB_PATH
        self.old_repos = get_settings().REPOS_DIR
        self.old_logs = get_settings().LOGS_DIR

        get_settings().DB_PATH = self.db_path
        get_settings().REPOS_DIR = self.temp_dir / "repos"
        get_settings().LOGS_DIR = self.temp_dir / "logs"

        await database.init_db(self.db_path)

        # Initialize real local Git repository to act as origin remote
        subprocess.run(["git", "init", "-b", "main"], cwd=str(self.origin_repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "E2E Bot"], cwd=str(self.origin_repo), check=True)
        subprocess.run(["git", "config", "user.email", "bot@example.com"], cwd=str(self.origin_repo), check=True)

        # Commit 1: Passing Python FastAPI app with unit test
        (self.origin_repo / "requirements.txt").write_text("fastapi>=0.100.0\nuvicorn>=0.20.0\n", encoding="utf-8")
        (self.origin_repo / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
        tests_dir = self.origin_repo / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("", encoding="utf-8")
        (tests_dir / "test_math.py").write_text(
            "import unittest\nclass TestApp(unittest.TestCase):\n    def test_ok(self):\n        self.assertEqual(1 + 1, 2)\n",
            encoding="utf-8",
        )

        subprocess.run(["git", "add", "."], cwd=str(self.origin_repo), check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit: passing tests"], cwd=str(self.origin_repo), check=True)
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.origin_repo), capture_output=True, text=True)
        self.sha1 = res.stdout.strip()

        self.webhook_secret = "e2e_secret_token_123"
        self.client = TestClient(app)
        self.orchestrator = BuildOrchestrator()

    async def asyncTearDown(self):
        get_settings().DB_PATH = self.old_db
        get_settings().REPOS_DIR = self.old_repos
        get_settings().LOGS_DIR = self.old_logs
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _sign(self, body_bytes: bytes) -> str:
        return "sha256=" + hmac.new(self.webhook_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

    async def test_full_acceptance_lifecycle(self):
        """Execute end-to-end acceptance flow as specified in Section 14."""
        repo_url = "https://github.com/e2e-org/e2e-project.git"

        # Intercept clone to pull from local origin repo during test
        from git_integration.repository import GitRepository
        def mock_clone_or_fetch(*args, **kwargs):
            r_id = kwargs.get("repo_id")
            tok = kwargs.get("credential_token")
            return GitRepository.clone_or_fetch(self.orchestrator.git_repo, str(self.origin_repo), r_id, tok)

        # ----------------------------------------------------
        # Step 1: Connect the repository
        # ----------------------------------------------------
        with patch("git_integration.repository.GitRepository.validate_access", return_value=True):
            repo_resp = self.client.post("/repositories", json={
                "url": repo_url,
                "default_branch": "main",
                "webhook_secret": self.webhook_secret,
            })
            self.assertEqual(repo_resp.status_code, 201)
            repo_data = repo_resp.json()
            repo_id = repo_data["id"]

        # ----------------------------------------------------
        # Step 2: Run initial pipeline (Build #1)
        # ----------------------------------------------------
        b1_rec = await database.create_build(
            repository_id=repo_id,
            commit_sha="HEAD",
            branch="main",
            trigger_type="manual",
            status="queued",
        )

        with patch.object(self.orchestrator.git_repo, "clone_or_fetch", side_effect=mock_clone_or_fetch), \
             patch("orchestrator.build_image", return_value="automator-test:b1"), \
             patch("deployment.manager.run_container", return_value="cid-1"), \
             patch("deployment.manager.stop_and_remove_container", return_value=True), \
             patch.object(self.orchestrator.deployment_mgr, "validate_candidate_health", AsyncMock(return_value=(True, None))):

            res1 = await self.orchestrator.execute_build(repo_id, b1_rec["id"], branch="main")
            self.assertTrue(res1["success"])

        # Confirm stack detection and Dockerfile generation
        b1_done = await database.get_build(b1_rec["id"])
        self.assertEqual(b1_done["status"], "success")
        self.assertEqual(b1_done["detected_stack"]["language"], "python")
        self.assertEqual(b1_done["detected_stack"]["framework"], "fastapi")
        self.assertEqual(b1_done["dockerfile_source"], "generated")

        # Confirm initial preview is current
        dep1 = await database.get_current_deployment(repo_id)
        self.assertIsNotNone(dep1)
        self.assertTrue(dep1["is_healthy"])
        self.assertTrue(dep1["is_current"])
        first_healthy_container = dep1["container_name"]

        # ----------------------------------------------------
        # Step 3: Push a small code change & send Webhook
        # ----------------------------------------------------
        (self.origin_repo / "new_feature.py").write_text("# Feature\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.origin_repo), check=True)
        subprocess.run(["git", "commit", "-m", "Commit 2: added new_feature"], cwd=str(self.origin_repo), check=True)
        res_sha2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.origin_repo), capture_output=True, text=True)
        sha2 = res_sha2.stdout.strip()

        # Send push webhook to API
        hook_payload = {
            "ref": "refs/heads/main",
            "after": sha2,
            "repository": {
                "name": repo_data["name"],
                "clone_url": repo_url,
                "owner": {"login": repo_data["owner"]},
            },
            "head_commit": {
                "id": sha2,
                "message": "Commit 2: added new_feature",
                "author": {"username": "e2e_tester"},
            },
        }
        raw_hook = json.dumps(hook_payload).encode("utf-8")
        sig2 = self._sign(raw_hook)

        hook_resp = self.client.post(
            "/webhooks/github",
            content=raw_hook,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Delivery": "delivery-e2e-002",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": sig2,
            },
        )
        self.assertEqual(hook_resp.status_code, 202)
        b2_id = hook_resp.json()["build_id"]
        self.assertEqual(hook_resp.json()["commit_sha"], sha2)

        # Execute Build #2
        with patch.object(self.orchestrator.git_repo, "clone_or_fetch", side_effect=mock_clone_or_fetch), \
             patch("orchestrator.build_image", return_value="automator-test:b2"), \
             patch("deployment.manager.run_container", return_value="cid-2"), \
             patch("deployment.manager.stop_and_remove_container", return_value=True), \
             patch.object(self.orchestrator.deployment_mgr, "validate_candidate_health", AsyncMock(return_value=(True, None))):

            res2 = await self.orchestrator.execute_build(repo_id, b2_id, branch="main", commit_sha=sha2)
            self.assertTrue(res2["success"])

        b2_done = await database.get_build(b2_id)
        self.assertEqual(b2_done["status"], "success")
        self.assertEqual(b2_done["commit_sha"], sha2)

        dep2 = await database.get_current_deployment(repo_id)
        self.assertIsNotNone(dep2)
        self.assertNotEqual(dep2["container_name"], first_healthy_container)
        second_healthy_container = dep2["container_name"]

        # ----------------------------------------------------
        # Step 4: Introduce a failing test
        # ----------------------------------------------------
        (self.origin_repo / "tests" / "test_math.py").write_text(
            "import unittest\nclass TestApp(unittest.TestCase):\n    def test_fail(self):\n        self.assertEqual(1 + 1, 999)\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=str(self.origin_repo), check=True)
        subprocess.run(["git", "commit", "-m", "Commit 3: broken test"], cwd=str(self.origin_repo), check=True)
        res_sha3 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.origin_repo), capture_output=True, text=True)
        sha3 = res_sha3.stdout.strip()

        # Build #3
        b3_rec = await database.create_build(
            repository_id=repo_id,
            commit_sha=sha3,
            branch="main",
            trigger_type="webhook",
            status="queued",
        )

        with patch.object(self.orchestrator.git_repo, "clone_or_fetch", side_effect=mock_clone_or_fetch), \
             patch("orchestrator.build_image", return_value="automator-test:b3"), \
             patch("deployment.manager.run_container", return_value="cid-3"), \
             patch("deployment.manager.stop_and_remove_container", return_value=True):

            res3 = await self.orchestrator.execute_build(repo_id, b3_rec["id"], branch="main", commit_sha=sha3)
            self.assertFalse(res3["success"])

        # Confirm build #3 failed
        b3_done = await database.get_build(b3_rec["id"])
        self.assertEqual(b3_done["status"], "failed")
        self.assertIn("AssertionError", b3_done["error_message"])

        # Crucial Verification: The healthy preview from Commit 2 REMAINS ACTIVE!
        dep_after_failure = await database.get_current_deployment(repo_id)
        self.assertEqual(dep_after_failure["container_name"], second_healthy_container)
        self.assertTrue(dep_after_failure["is_healthy"])
        self.assertTrue(dep_after_failure["is_current"])

        # ----------------------------------------------------
        # Step 5: Push a corrected change & confirm zero-downtime switch
        # ----------------------------------------------------
        (self.origin_repo / "tests" / "test_math.py").write_text(
            "import unittest\nclass TestApp(unittest.TestCase):\n    def test_fixed(self):\n        self.assertEqual(1 + 1, 2)\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=str(self.origin_repo), check=True)
        subprocess.run(["git", "commit", "-m", "Commit 4: fixed test"], cwd=str(self.origin_repo), check=True)
        res_sha4 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.origin_repo), capture_output=True, text=True)
        sha4 = res_sha4.stdout.strip()

        b4_rec = await database.create_build(
            repository_id=repo_id,
            commit_sha=sha4,
            branch="main",
            trigger_type="webhook",
            status="queued",
        )

        with patch.object(self.orchestrator.git_repo, "clone_or_fetch", side_effect=mock_clone_or_fetch), \
             patch("orchestrator.build_image", return_value="automator-test:b4"), \
             patch("deployment.manager.run_container", return_value="cid-4"), \
             patch("deployment.manager.stop_and_remove_container", return_value=True), \
             patch.object(self.orchestrator.deployment_mgr, "validate_candidate_health", AsyncMock(return_value=(True, None))):

            res4 = await self.orchestrator.execute_build(repo_id, b4_rec["id"], branch="main", commit_sha=sha4)
            self.assertTrue(res4["success"])

        b4_done = await database.get_build(b4_rec["id"])
        self.assertEqual(b4_done["status"], "success")
        self.assertEqual(b4_done["commit_sha"], sha4)

        # Confirm safe zero-downtime switch to candidate 4
        dep4 = await database.get_current_deployment(repo_id)
        self.assertTrue(dep4["is_healthy"])
        self.assertTrue(dep4["is_current"])
        self.assertNotEqual(dep4["container_name"], second_healthy_container)


if __name__ == "__main__":
    unittest.main()
