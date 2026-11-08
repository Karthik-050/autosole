"""Automated tests for FastAPI REST API endpoints and GitHub webhook handling."""

import hashlib
import hmac
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from config import get_settings
import database
from server import app


class TestAPIEndpoints(unittest.TestCase):
    """Test REST API routes, repository CRUD, builds, and webhooks."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = Path(tempfile.mkdtemp())
        cls.db_path = cls.temp_dir / "test_api.db"
        cls.old_db_path = get_settings().DB_PATH
        get_settings().DB_PATH = cls.db_path

        import asyncio
        asyncio.run(database.init_db(cls.db_path))
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        get_settings().DB_PATH = cls.old_db_path
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_get_index_html(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Automator", resp.text)

    def test_connect_repository_success_and_validation(self):
        # 1. Invalid URL scheme (SSH)
        res_bad = self.client.post("/repositories", json={"url": "git@github.com:foo/bar.git"})
        self.assertEqual(res_bad.status_code, 400)

        # 2. Valid HTTPS repo
        with patch("git_integration.repository.GitRepository.validate_access", return_value=True):
            resp = self.client.post("/repositories", json={
                "url": "https://github.com/octocat/hello-world",
                "default_branch": "main",
                "credential_token": "private-github-token-test-only",
                "webhook_secret": "my-test-secret-1234",
            })
            self.assertEqual(resp.status_code, 201)
            data = resp.json()
            self.assertEqual(data["name"], "hello-world")
            self.assertEqual(data["owner"], "octocat")
            self.assertEqual(data["default_branch"], "main")
            self.assertTrue(data["credential_configured"])
            self.assertTrue(data["webhook_secret_configured"])
            self.assertNotIn("credential_id", data)
            self.assertNotIn("webhook_secret", data)
            self.assertNotIn("private-github-token-test-only", resp.text)
            self.assertNotIn("my-test-secret-1234", resp.text)
            self.repo_id = data["id"]

    def test_list_and_get_repository(self):
        # List
        resp = self.client.get("/repositories")
        self.assertEqual(resp.status_code, 200)
        repos = resp.json()
        self.assertTrue(len(repos) >= 1)
        target = repos[0]
        self.assertNotIn("credential_id", target)
        self.assertNotIn("webhook_secret", target)

        # Get by ID
        resp_single = self.client.get(f"/repositories/{target['id']}")
        self.assertEqual(resp_single.status_code, 200)
        self.assertEqual(resp_single.json()["name"], target["name"])
        self.assertNotIn("credential_id", resp_single.json())
        self.assertNotIn("webhook_secret", resp_single.json())

    def test_trigger_build_endpoint(self):
        repos = self.client.get("/repositories").json()
        repo_id = repos[0]["id"]

        with patch("orchestrator.BuildOrchestrator.execute_build", new_callable=AsyncMock):
            resp = self.client.post(f"/repositories/{repo_id}/builds", json={"branch": "main"})
            self.assertEqual(resp.status_code, 202)
            data = resp.json()
            self.assertEqual(data["repository_id"], repo_id)
            self.assertEqual(data["status"], "queued")
            self.build_id = data["id"]

            # Query build
            b_resp = self.client.get(f"/builds/{self.build_id}")
            self.assertEqual(b_resp.status_code, 200)
            self.assertEqual(b_resp.json()["id"], self.build_id)

    def test_webhook_flow_with_signature(self):
        repos = self.client.get("/repositories").json()
        target_repo = repos[0]
        secret = "my-test-secret-1234"

        webhook_status = self.client.get(f"/repositories/{target_repo['id']}/webhook-status")
        self.assertEqual(webhook_status.status_code, 200)
        self.assertTrue(webhook_status.json()["webhook_secret_configured"])
        self.assertNotIn("webhook_secret", webhook_status.json())

        payload = {
            "ref": "refs/heads/main",
            "after": "deadbeef1234567890abcdef1234567890abcdef",
            "repository": {
                "name": target_repo["name"],
                "clone_url": target_repo["url"],
                "owner": {"login": target_repo["owner"]},
            },
            "head_commit": {
                "id": "deadbeef1234567890abcdef1234567890abcdef",
                "message": "Update dependencies",
                "author": {"username": "tester"},
            },
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        sig = "sha256=" + hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

        with patch("orchestrator.BuildOrchestrator.execute_build", new_callable=AsyncMock):
            # Missing signatures must not queue builds.
            resp_missing_sig = self.client.post(
                "/webhooks/github",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Delivery": "delivery-missing-signature",
                    "X-GitHub-Event": "push",
                },
            )
            self.assertEqual(resp_missing_sig.status_code, 401)

            # 1. Successful Webhook trigger
            resp = self.client.post(
                "/webhooks/github",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Delivery": "delivery-unique-1234",
                    "X-GitHub-Event": "push",
                    "X-Hub-Signature-256": sig,
                },
            )
            self.assertEqual(resp.status_code, 202)
            res_data = resp.json()
            self.assertEqual(res_data["status"], "queued")
            self.assertEqual(res_data["commit_sha"], "deadbeef1234567890abcdef1234567890abcdef")

            # 2. Duplicate delivery deduplication
            resp_dup = self.client.post(
                "/webhooks/github",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Delivery": "delivery-unique-1234",
                    "X-GitHub-Event": "push",
                    "X-Hub-Signature-256": sig,
                },
            )
            self.assertEqual(resp_dup.status_code, 200)
            self.assertEqual(resp_dup.json()["status"], "already_processed")

            # 3. Invalid signature rejection
            resp_bad_sig = self.client.post(
                "/webhooks/github",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Delivery": "delivery-unique-5678",
                    "X-GitHub-Event": "push",
                    "X-Hub-Signature-256": "sha256=wrongsignature",
                },
            )
            self.assertEqual(resp_bad_sig.status_code, 401)


if __name__ == "__main__":
    unittest.main()
