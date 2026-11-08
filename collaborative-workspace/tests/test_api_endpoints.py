import sys
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.main import app

class TestApiEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_root_endpoint(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("Unified Automator & Collaborative Workspace API", data["message"])

    def test_backward_compatible_workspaces_endpoints(self):
        # 1. Create workspace
        create_resp = self.client.post("/workspaces")
        self.assertEqual(create_resp.status_code, 200)
        wid = create_resp.json()["workspace_id"]

        # 2. List workspaces
        list_resp = self.client.get("/workspaces")
        self.assertEqual(list_resp.status_code, 200)
        self.assertIn(wid, list_resp.json()["workspaces"])

        # 3. Create file
        file_resp = self.client.post(f"/workspaces/{wid}/files", params={"filename": "test.py"})
        self.assertEqual(file_resp.status_code, 200)

        # 4. Write file
        write_resp = self.client.post(f"/workspaces/{wid}/write", params={"filename": "test.py", "content": "x = 42\n"})
        self.assertEqual(write_resp.status_code, 200)

        # 5. Read file
        read_resp = self.client.get(f"/workspaces/{wid}/read", params={"filename": "test.py"})
        self.assertEqual(read_resp.status_code, 200)
        self.assertEqual(read_resp.json()["content"], "x = 42\n")

        # 6. Delete file
        del_file_resp = self.client.delete(f"/workspaces/{wid}/files", params={"filename": "test.py"})
        self.assertEqual(del_file_resp.status_code, 200)

        # 7. Delete workspace
        del_ws_resp = self.client.delete(f"/workspaces/{wid}")
        self.assertEqual(del_ws_resp.status_code, 200)

    def test_modular_api_endpoints(self):
        # Dashboard stats
        resp = self.client.get("/api/dashboard/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("projects", data)
        self.assertIn("services", data)

        # Projects list
        resp = self.client.get("/api/projects")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("projects", resp.json())

        # Docker status
        resp = self.client.get("/api/docker/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("status", resp.json())

        # Jenkins status
        resp = self.client.get("/api/jenkins/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("status", resp.json())

        # Deployments list
        resp = self.client.get("/api/deployments")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("deployments", resp.json())

        # Settings
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200)
        settings_data = resp.json()["settings"]
        self.assertIn("jenkins_token_configured", settings_data)
        # Token must NOT be exposed
        self.assertNotIn("jenkins_api_token", settings_data)

        # Test settings connections
        resp = self.client.post("/api/settings/test-docker")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post("/api/settings/test-jenkins")
        self.assertEqual(resp.status_code, 200)

if __name__ == "__main__":
    unittest.main()
