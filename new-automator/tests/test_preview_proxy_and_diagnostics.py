"""Automated unit and integration tests for Automator Preview Proxy and Diagnostics."""

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import threading
import unittest
from unittest.mock import patch
import uuid

from starlette.testclient import TestClient

from config import Settings, get_settings
import database
from deployment.diagnostics import (
    format_diagnostics_report,
    get_preview_diagnostics,
    inspect_docker_container,
    is_port_listening,
)
from deployment.proxy import inject_base_href, rewrite_redirect_location
from server import app


class MockUpstreamHandler(BaseHTTPRequestHandler):
    """Simple HTTP server handler for simulating candidate containers."""

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><head><title>App</title></head><body><h1>Hello World</h1></body></html>")
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/dashboard")
            self.end_headers()
        elif self.path == "/absolute-redirect":
            host = self.headers.get("Host", "127.0.0.1")
            self.send_response(302)
            self.send_header("Location", f"http://{host}/account")
            self.end_headers()
        elif self.path == "/headers":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            prefix = self.headers.get("X-Forwarded-Prefix", "")
            f_host = self.headers.get("X-Forwarded-Host", "")
            self.wfile.write(f'{{"prefix": "{prefix}", "f_host": "{f_host}"}}'.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Quiet logging during tests


class TestPreviewConfigAndDatabase(unittest.IsolatedAsyncioTestCase):
    """Test configuration settings and database migrations for preview routing."""

    async def asyncSetUp(self):
        self.db_path = ":memory:"
        await database.init_db(self.db_path)

    def test_public_base_url_config(self):
        s = Settings()
        self.assertEqual(s.PUBLIC_BASE_URL, "http://localhost:8000")

        with patch.dict(os.environ, {"AUTOMATOR_PUBLIC_BASE_URL": "https://preview.mydevops.io"}):
            s_custom = Settings()
            self.assertEqual(s_custom.PUBLIC_BASE_URL, "https://preview.mydevops.io")

    async def test_container_port_database_persistence(self):
        uid = uuid.uuid4().hex[:8]
        repo_name = f"app-{uid}"
        repo = await database.create_repository(
            url=f"https://github.com/acme/{repo_name}.git",
            provider="github.com",
            name=repo_name,
            owner="acme",
            repo_id=f"repo-{uid}",
        )

        dep = await database.create_deployment(
            repository_id=repo["id"],
            container_name=f"test-container-{uid}",
            host_port=5200,
            container_port=8080,
            status="running",
            is_healthy=True,
            is_current=True,
        )

        self.assertEqual(dep["container_port"], 8080)
        self.assertEqual(dep["host_port"], 5200)
        self.assertTrue(dep["is_healthy"])

        # Test find_active_deployment by ID
        found_by_id = await database.find_active_deployment(repo["id"])
        self.assertIsNotNone(found_by_id)
        self.assertEqual(found_by_id["host_port"], 5200)
        self.assertEqual(found_by_id["container_port"], 8080)

        # Test find_active_deployment by repo name
        found_by_name = await database.find_active_deployment(repo_name)
        self.assertIsNotNone(found_by_name)
        self.assertEqual(found_by_name["id"], dep["id"])


class TestPreviewProxyRouting(unittest.TestCase):
    """Test reverse proxy request handling, redirects, rewrites, and error responses."""

    @classmethod
    def setUpClass(cls):
        # Start background mock upstream server
        cls.server = HTTPServer(("127.0.0.1", 0), MockUpstreamHandler)
        cls.port = cls.server.server_port
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        asyncio.run(database.init_db())

    def test_trailing_slash_redirection(self):
        resp = self.client.get("/preview/my-test-repo", follow_redirects=False)
        self.assertEqual(resp.status_code, 307)
        self.assertEqual(resp.headers.get("location"), "/preview/my-test-repo/")

    def test_trailing_slash_redirection_preserves_query(self):
        resp = self.client.get("/preview/my-test-repo?tab=settings&view=active", follow_redirects=False)
        self.assertEqual(resp.status_code, 307)
        self.assertEqual(resp.headers.get("location"), "/preview/my-test-repo/?tab=settings&view=active")

    def test_preview_unavailable_503(self):
        resp = self.client.get("/preview/nonexistent-repo-999/")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("Deployment Candidate Starting", resp.text)
        self.assertIn("nonexistent-repo-999", resp.text)

    def test_location_rewriting_helpers(self):
        prefix = "/preview/my-app"
        hosts = [f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"]

        # Root-relative redirect
        rewritten_rel = rewrite_redirect_location("/dashboard", prefix, hosts)
        self.assertEqual(rewritten_rel, "/preview/my-app/dashboard")

        # Absolute upstream redirect
        rewritten_abs = rewrite_redirect_location(f"http://127.0.0.1:{self.port}/profile", prefix, hosts)
        self.assertEqual(rewritten_abs, "/preview/my-app/profile")

        # External redirect unchanged
        external = "https://accounts.google.com/signin"
        self.assertEqual(rewrite_redirect_location(external, prefix, hosts), external)

    def test_html_base_href_injection(self):
        html = "<html><head><title>App</title></head><body><h1>Content</h1></body></html>"
        injected = inject_base_href(html, "/preview/my-app/")
        self.assertIn('<base href="/preview/my-app/">', injected)

        # Existing <base> preserved
        already_has_base = '<html><head><base href="/custom/"><title>App</title></head><body></body></html>'
        self.assertEqual(inject_base_href(already_has_base, "/preview/my-app/"), already_has_base)

    def test_upstream_proxying_with_mock_container(self):
        # Register a mock deployment pointing to our mock server port
        uid = uuid.uuid4().hex[:8]
        repo_id = f"test-proxy-{uid}"
        asyncio.run(
            database.create_repository(
                url=f"https://github.com/mock/{repo_id}.git",
                provider="github.com",
                name=repo_id,
                owner="mock",
                repo_id=repo_id,
            )
        )
        asyncio.run(
            database.create_deployment(
                repository_id=repo_id,
                container_name=f"preview-{repo_id}",
                host_port=self.port,
                container_port=80,
                status="running",
                is_healthy=True,
                is_current=True,
            )
        )

        # 1. Test HTML proxying and base tag injection
        resp = self.client.get(f"/preview/{repo_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Hello World", resp.text)
        self.assertIn(f'<base href="/preview/{repo_id}/">', resp.text)

        # 2. Test forwarded prefix headers
        h_resp = self.client.get(f"/preview/{repo_id}/headers")
        self.assertEqual(h_resp.status_code, 200)
        data = h_resp.json()
        self.assertEqual(data["prefix"], f"/preview/{repo_id}")

        # 3. Test Location rewrite on redirect
        r_resp = self.client.get(f"/preview/{repo_id}/redirect", follow_redirects=False)
        self.assertEqual(r_resp.status_code, 302)
        self.assertEqual(r_resp.headers.get("location"), f"/preview/{repo_id}/dashboard")

        # 4. Test absolute Location rewrite
        abs_resp = self.client.get(f"/preview/{repo_id}/absolute-redirect", follow_redirects=False)
        self.assertEqual(abs_resp.status_code, 302)
        self.assertEqual(abs_resp.headers.get("location"), f"/preview/{repo_id}/account")

    def test_connection_error_returns_502(self):
        # Deployment pointing to an unused port
        uid = uuid.uuid4().hex[:8]
        dead_repo_id = f"dead-port-{uid}"
        asyncio.run(
            database.create_repository(
                url=f"https://github.com/mock/{dead_repo_id}.git",
                provider="github.com",
                name=dead_repo_id,
                owner="mock",
                repo_id=dead_repo_id,
            )
        )
        asyncio.run(
            database.create_deployment(
                repository_id=dead_repo_id,
                container_name=f"preview-{dead_repo_id}",
                host_port=59999,
                container_port=5000,
                status="running",
                is_healthy=True,
                is_current=True,
            )
        )

        resp = self.client.get(f"/preview/{dead_repo_id}/", headers={"accept": "application/json"})
        self.assertEqual(resp.status_code, 502)
        data = resp.json()
        self.assertEqual(data["host_port"], 59999)
        self.assertIn("direct_url", data)
        self.assertEqual(data["direct_url"], "http://localhost:59999/")


class TestPreviewDiagnostics(unittest.TestCase):
    """Test diagnostics reporting and REST endpoint."""

    def setUp(self):
        self.client = TestClient(app)
        asyncio.run(database.init_db())

    def test_diagnostics_not_found(self):
        report = asyncio.run(get_preview_diagnostics("unknown-xyz-999"))
        self.assertEqual(report["status"], "not_found")
        self.assertIsNone(report["deployment"])
        self.assertTrue(len(report["recommendations"]) > 0)

    def test_diagnostics_for_deployment(self):
        uid = uuid.uuid4().hex[:8]
        repo_id = f"diag-test-{uid}"
        asyncio.run(
            database.create_repository(
                url=f"https://github.com/diag/{repo_id}.git",
                provider="github.com",
                name=repo_id,
                owner="diag",
                repo_id=repo_id,
            )
        )
        asyncio.run(
            database.create_deployment(
                repository_id=repo_id,
                container_name=f"preview-{repo_id}",
                host_port=5188,
                container_port=3000,
                status="running",
                is_healthy=True,
                is_current=True,
            )
        )

        report = asyncio.run(get_preview_diagnostics(repo_id))
        self.assertIn("status", report)
        self.assertIn("deployment", report)
        self.assertEqual(report["deployment"]["host_port"], 5188)
        self.assertEqual(report["deployment"]["container_port"], 3000)
        self.assertEqual(report["direct_container_url"], "http://localhost:5188/")

        # Test ASCII report formatter
        text_report = format_diagnostics_report(report)
        self.assertIn("AUTOMATOR PREVIEW DIAGNOSTICS", text_report)
        self.assertIn("Host 5188 -> Container 3000", text_report)

        # Test REST API endpoint
        api_resp = self.client.get(f"/api/diagnostics/preview/{repo_id}")
        self.assertEqual(api_resp.status_code, 200)
        data = api_resp.json()
        self.assertEqual(data["deployment"]["host_port"], 5188)
        self.assertEqual(data["deployment"]["container_port"], 3000)


if __name__ == "__main__":
    unittest.main()
