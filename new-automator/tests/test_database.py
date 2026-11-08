"""Automated tests for asynchronous SQLite persistence and migrations."""

from pathlib import Path
import shutil
import tempfile
import unittest

import database


class TestDatabaseLayer(unittest.IsolatedAsyncioTestCase):
    """Test SQLite schema initialization, CRUD operations, and constraints."""

    async def asyncSetUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "test_persistence.db"
        await database.init_db(self.db_path)

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_repository_lifecycle(self):
        async with database.get_connection(self.db_path) as conn:
            repo = await database.create_repository(
                url="https://github.com/my-org/my-app.git",
                provider="github.com",
                name="my-app",
                owner="my-org",
                default_branch="develop",
                is_private=True,
                credential_id="sec-token",
                conn=conn,
            )
            self.assertEqual(repo["name"], "my-app")
            self.assertTrue(repo["is_private"])

            # Read by ID
            by_id = await database.get_repository(repo["id"], conn=conn)
            self.assertIsNotNone(by_id)
            self.assertEqual(by_id["owner"], "my-org")

            # Update
            updated = await database.update_repository(repo["id"], default_branch="main", conn=conn)
            self.assertEqual(updated["default_branch"], "main")

            # Delete
            deleted = await database.delete_repository(repo["id"], conn=conn)
            self.assertTrue(deleted)
            self.assertIsNone(await database.get_repository(repo["id"], conn=conn))

    async def test_build_consecutive_numbering_and_latest(self):
        async with database.get_connection(self.db_path) as conn:
            repo = await database.create_repository(
                url="https://github.com/org/repo.git",
                provider="github.com",
                name="repo",
                owner="org",
                conn=conn,
            )
            repo_id = repo["id"]

            b1 = await database.create_build(
                repository_id=repo_id,
                commit_sha="c1",
                branch="main",
                status="failed",
                conn=conn,
            )
            self.assertEqual(b1["build_number"], 1)

            b2 = await database.create_build(
                repository_id=repo_id,
                commit_sha="c2",
                branch="main",
                status="success",
                conn=conn,
            )
            self.assertEqual(b2["build_number"], 2)

            b3 = await database.create_build(
                repository_id=repo_id,
                commit_sha="c3",
                branch="main",
                status="running",
                conn=conn,
            )
            self.assertEqual(b3["build_number"], 3)

            # Latest successful build should be b2
            latest_succ = await database.get_latest_successful_build(repo_id, conn=conn)
            self.assertIsNotNone(latest_succ)
            self.assertEqual(latest_succ["id"], b2["id"])
            self.assertEqual(latest_succ["build_number"], 2)

    async def test_deployment_atomic_switching(self):
        async with database.get_connection(self.db_path) as conn:
            repo = await database.create_repository(
                url="https://github.com/org/switch.git",
                provider="github.com",
                name="switch",
                owner="org",
                conn=conn,
            )
            repo_id = repo["id"]

            # Deployment 1
            d1 = await database.create_deployment(
                repository_id=repo_id,
                container_name="preview-v1",
                host_port=5101,
                is_healthy=True,
                is_current=True,
                conn=conn,
            )
            self.assertTrue(d1["is_current"])

            # Deployment 2 made current
            d2 = await database.create_deployment(
                repository_id=repo_id,
                container_name="preview-v2",
                host_port=5102,
                is_healthy=True,
                is_current=True,
                conn=conn,
            )
            self.assertTrue(d2["is_current"])

            # Check that d1 is no longer current
            d1_refreshed = await database.get_deployment(d1["id"], conn=conn)
            self.assertFalse(d1_refreshed["is_current"])

            # Check active deployment query
            active = await database.get_current_deployment(repo_id, conn=conn)
            self.assertIsNotNone(active)
            self.assertEqual(active["id"], d2["id"])


if __name__ == "__main__":
    unittest.main()
