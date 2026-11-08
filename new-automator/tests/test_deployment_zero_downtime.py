"""Automated tests for zero-downtime deployment, candidate validation, and rollback."""

import asyncio
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import database
from deployment.manager import DeploymentManager, DeploymentResult, find_available_port


class TestZeroDowntimeDeployment(unittest.IsolatedAsyncioTestCase):
    """Test candidate deployment, health verification, and rollback."""

    async def asyncSetUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "test_deploy.db"
        self.old_db_path = database.get_settings().DB_PATH
        database.get_settings().DB_PATH = self.db_path
        await database.init_db(self.db_path)

        # Create a test repository
        self.repo = await database.create_repository(
            url="https://github.com/example/web-app.git",
            provider="github.com",
            name="web-app",
            owner="example",
            repo_id="test-repo-deploy",
        )
        self.repo_id = self.repo["id"]

        # Create build records
        await database.create_build(
            repository_id=self.repo_id,
            commit_sha="a1b2c3d",
            branch="main",
            build_id="build-001",
        )
        await database.create_build(
            repository_id=self.repo_id,
            commit_sha="e5f6a7b",
            branch="main",
            build_id="build-002",
        )

        self.mgr = DeploymentManager(health_check_timeout=5, health_poll_interval=0.1)

    async def asyncTearDown(self):
        database.get_settings().DB_PATH = self.old_db_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_find_available_port(self):
        port = find_available_port(start_port=5200, max_port=5300)
        self.assertTrue(5200 <= port < 5300)

    @patch("deployment.manager.run_container", return_value="docker-container-id-1")
    @patch("deployment.manager.stop_and_remove_container", return_value=True)
    async def test_successful_first_deployment(self, mock_stop, mock_run):
        with patch.object(self.mgr, "validate_candidate_health", AsyncMock(return_value=(True, None))):
            res: DeploymentResult = await self.mgr.deploy_candidate(
                repo_id=self.repo_id,
                build_id="build-001",
                image_tag="automator-app:v1",
                container_port=8000,
            )

            self.assertTrue(res.success)
            self.assertTrue(res.is_switched)
            self.assertIn("preview-", res.container_name)
            self.assertIsNotNone(res.host_port)
            self.assertIsNone(res.previous_container_stopped)

            # Check database deployment record
            current = await database.get_current_deployment(self.repo_id)
            self.assertIsNotNone(current)
            self.assertEqual(current["container_name"], res.container_name)
            self.assertTrue(current["is_current"])
            self.assertTrue(current["is_healthy"])

    @patch("deployment.manager.run_container", return_value="docker-container-id-2")
    @patch("deployment.manager.stop_and_remove_container", return_value=True)
    async def test_candidate_failure_preserves_healthy_previous_container(self, mock_stop, mock_run):
        # Step 1: Establish healthy initial deployment
        with patch.object(self.mgr, "validate_candidate_health", AsyncMock(return_value=(True, None))):
            initial_res = await self.mgr.deploy_candidate(
                repo_id=self.repo_id,
                build_id="build-001",
                image_tag="automator-app:v1",
                container_port=8000,
            )
            self.assertTrue(initial_res.success)
            initial_container = initial_res.container_name

        # Step 2: Attempt deploying a second candidate that FAILS health checks
        with patch.object(self.mgr, "validate_candidate_health", AsyncMock(return_value=(False, "Connection refused 500"))):
            failed_res = await self.mgr.deploy_candidate(
                repo_id=self.repo_id,
                build_id="build-002",
                image_tag="automator-app:v2-broken",
                container_port=8000,
            )

            # Candidate must be reported failed
            self.assertFalse(failed_res.success)
            self.assertIn("Connection refused", failed_res.error_message)

            # Crucial: Failed candidate was stopped and removed
            mock_stop.assert_called_with(failed_res.container_name)

            # Crucial: Database still points to original healthy deployment
            current = await database.get_current_deployment(self.repo_id)
            self.assertIsNotNone(current)
            self.assertEqual(current["container_name"], initial_container)
            self.assertEqual(current["image_tag"], "automator-app:v1")
            self.assertTrue(current["is_healthy"])
            self.assertTrue(current["is_current"])

    @patch("deployment.manager.run_container", return_value="docker-container-id-3")
    @patch("deployment.manager.stop_and_remove_container", return_value=True)
    async def test_successful_replacement_drains_old_container(self, mock_stop, mock_run):
        with patch.object(self.mgr, "validate_candidate_health", AsyncMock(return_value=(True, None))):
            dep1 = await self.mgr.deploy_candidate(
                repo_id=self.repo_id,
                build_id="build-001",
                image_tag="automator-app:v1",
                container_port=8000,
            )

            dep2 = await self.mgr.deploy_candidate(
                repo_id=self.repo_id,
                build_id="build-002",
                image_tag="automator-app:v2",
                container_port=8000,
            )

            self.assertTrue(dep2.success)
            # Old container was drained and stopped
            self.assertEqual(dep2.previous_container_stopped, dep1.container_name)
            mock_stop.assert_any_call(dep1.container_name, timeout=10)

            current = await database.get_current_deployment(self.repo_id)
            self.assertEqual(current["container_name"], dep2.container_name)
            self.assertEqual(current["image_tag"], "automator-app:v2")

    @patch("deployment.manager.run_container", return_value="docker-container-id-4")
    @patch("deployment.manager.stop_and_remove_container", return_value=True)
    async def test_rollback(self, mock_stop, mock_run):
        with patch.object(self.mgr, "validate_candidate_health", AsyncMock(return_value=(True, None))):
            await self.mgr.deploy_candidate(
                repo_id=self.repo_id,
                build_id="build-001",
                image_tag="automator-app:v1",
                container_port=8000,
            )
            await self.mgr.deploy_candidate(
                repo_id=self.repo_id,
                build_id="build-002",
                image_tag="automator-app:v2",
                container_port=8000,
            )

            # Roll back
            rb_res = await self.mgr.rollback(self.repo_id)
            self.assertTrue(rb_res.success)

            current = await database.get_current_deployment(self.repo_id)
            self.assertEqual(current["image_tag"], "automator-app:v1")


if __name__ == "__main__":
    unittest.main()
