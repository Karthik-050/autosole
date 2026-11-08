"""Automated test suite verifying the 14 mandatory CI/CD failure cases and edge cases:

1. Python project with requirements.txt
2. Python project with pyproject.toml
3. Python project with no dependency manifest
4. ZIP containing files at its root
5. ZIP containing an extra top-level directory
6. Missing Dockerfile and invalid project paths
7. .dockerignore excluding required files
8. Valid and invalid Git repository URLs
9. Git clone and authentication failures
10. Docker daemon unavailable
11. Jenkins unavailable or authentication failure
12. Jenkins job creation/update and build failure
13. Deployment health-check failure
14. Missing or invalid configuration
"""

import asyncio
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from analyzer.detector import DetectionResult, detect_project
from config import Settings, get_settings
from deployment.manager import DeploymentManager
from docker.generator import (
    DEFAULT_DOCKERIGNORE,
    build_image,
    ensure_dockerignore,
    generate_dockerfile,
    inspect_dockerignore,
    validate_build_prerequisites,
)
from git_integration.repository import GitAuthenticationError, GitError, GitNetworkError, GitRepository
from git_integration.validators import validate_git_url
from jenkins_automation import client as jenkins_client
from jenkins_automation.manager import ensure_jenkins_running, is_docker_daemon_available
from project_manager import extract_project, find_project_root


class TestCICDSystemValidation(unittest.TestCase):
    """Test suite for the 14 CI/CD system failure and validation requirements."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="automator_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ------------------------------------------------------------
    # 1. Python project with requirements.txt
    # ------------------------------------------------------------
    def test_case_1_python_project_with_requirements_txt(self):
        app_file = self.temp_dir / "app.py"
        app_file.write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")
        req_file = self.temp_dir / "requirements.txt"
        req_file.write_text("flask>=3.0.0\n", encoding="utf-8")

        det = detect_project(self.temp_dir)
        self.assertEqual(det.language, "python")
        self.assertEqual(det.dependency_manager, "pip")
        self.assertTrue(det.has_requirements_file)
        self.assertEqual(det.framework, "flask")

        df_path = generate_dockerfile(self.temp_dir, det)
        df_content = df_path.read_text(encoding="utf-8")
        self.assertIn("COPY requirements.txt ./", df_content)
        self.assertIn("RUN pip install --no-cache-dir -r requirements.txt", df_content)

    # ------------------------------------------------------------
    # 2. Python project with pyproject.toml
    # ------------------------------------------------------------
    def test_case_2_python_project_with_pyproject_toml(self):
        app_file = self.temp_dir / "main.py"
        app_file.write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
        toml_file = self.temp_dir / "pyproject.toml"
        toml_file.write_text(
            '[build-system]\nrequires = ["setuptools"]\n[project]\nname = "myapi"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )

        det = detect_project(self.temp_dir)
        self.assertEqual(det.language, "python")
        self.assertEqual(det.dependency_manager, "pyproject")
        self.assertTrue(det.has_pyproject_file)
        self.assertFalse(det.has_requirements_file)

        df_path = generate_dockerfile(self.temp_dir, det)
        df_content = df_path.read_text(encoding="utf-8")
        # Must copy pyproject.toml and NOT assume requirements.txt
        self.assertIn("COPY pyproject.toml ./", df_content)
        self.assertIn("RUN pip install --no-cache-dir .", df_content)
        self.assertNotIn("COPY requirements.txt", df_content)

    # ------------------------------------------------------------
    # 3. Python project with no dependency manifest
    # ------------------------------------------------------------
    def test_case_3_python_project_no_dependency_manifest(self):
        app_file = self.temp_dir / "app.py"
        app_file.write_text("import sys\nprint('Hello standard library')\n", encoding="utf-8")

        det = detect_project(self.temp_dir)
        self.assertEqual(det.language, "python")
        self.assertEqual(det.dependency_manager, "none")
        self.assertFalse(det.has_requirements_file)
        self.assertFalse(det.has_pyproject_file)

        df_path = generate_dockerfile(self.temp_dir, det)
        df_content = df_path.read_text(encoding="utf-8")
        # Must not copy or install nonexistent requirements.txt
        self.assertNotIn("COPY requirements.txt", df_content)
        self.assertNotIn("-r requirements.txt", df_content)
        self.assertIn("COPY . .", df_content)
        self.assertIn("CMD", df_content)

    # ------------------------------------------------------------
    # 4. ZIP containing files at its root
    # ------------------------------------------------------------
    def test_case_4_zip_containing_files_at_root(self):
        zip_path = self.temp_dir / "root_project.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("app.py", "print('root app')")
            zf.writestr("requirements.txt", "requests\n")

        dest_dir = self.temp_dir / "extracted_root"
        extracted = extract_project(zip_path, target_dir=dest_dir)

        self.assertEqual(extracted, dest_dir)
        self.assertTrue((dest_dir / "app.py").exists())
        self.assertTrue((dest_dir / "requirements.txt").exists())

    # ------------------------------------------------------------
    # 5. ZIP containing an extra top-level directory
    # ------------------------------------------------------------
    def test_case_5_zip_containing_extra_top_level_directory(self):
        zip_path = self.temp_dir / "nested_project.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("wrapper_folder/inner_folder/app.py", "print('nested app')")
            zf.writestr("wrapper_folder/inner_folder/requirements.txt", "flask\n")
            # Include macOS noise to simulate real-world archives
            zf.writestr("__MACOSX/._app.py", "metadata")
            zf.writestr("wrapper_folder/.DS_Store", "junk")

        dest_dir = self.temp_dir / "extracted_nested"
        extracted = extract_project(zip_path, target_dir=dest_dir)

        self.assertEqual(extracted, dest_dir)
        # Both app.py and requirements.txt must be at the extracted project root!
        self.assertTrue((dest_dir / "app.py").exists(), "app.py should be at the root")
        self.assertTrue((dest_dir / "requirements.txt").exists(), "requirements.txt should be at the root")
        self.assertFalse((dest_dir / "wrapper_folder").exists())

    # ------------------------------------------------------------
    # 6. Missing Dockerfile and invalid project paths
    # ------------------------------------------------------------
    def test_case_6_missing_dockerfile_and_invalid_project_paths(self):
        nonexistent_dir = self.temp_dir / "does_not_exist"
        with self.assertRaises(FileNotFoundError):
            validate_build_prerequisites(nonexistent_dir, nonexistent_dir / "Dockerfile")

        # Project exists but Dockerfile missing
        valid_dir = self.temp_dir / "empty_proj"
        valid_dir.mkdir()
        with self.assertRaises(FileNotFoundError):
            validate_build_prerequisites(valid_dir, valid_dir / "Dockerfile")

        # Dockerfile references missing requirements.txt in COPY instruction
        df = valid_dir / "Dockerfile"
        df.write_text("FROM python:3.12-slim\nCOPY requirements.txt .\nCMD [\"python\"]\n", encoding="utf-8")
        with self.assertRaises(FileNotFoundError) as ctx:
            validate_build_prerequisites(valid_dir, df)
        self.assertIn("requirements.txt", str(ctx.exception))
        self.assertIn("does not exist in build context", str(ctx.exception))

    # ------------------------------------------------------------
    # 7. .dockerignore excluding required files
    # ------------------------------------------------------------
    def test_case_7_dockerignore_excluding_required_files(self):
        proj_dir = self.temp_dir / "dockerignore_proj"
        proj_dir.mkdir()
        ign_file = proj_dir / ".dockerignore"
        ign_file.write_text("requirements.txt\n*.py\n", encoding="utf-8")

        conflicts = inspect_dockerignore(ign_file)
        self.assertIn("requirements.txt", conflicts)
        self.assertIn("app.py", conflicts)

        # ensure_dockerignore patches existing .dockerignore with overrides
        ensure_dockerignore(proj_dir)
        patched_content = ign_file.read_text(encoding="utf-8")
        self.assertIn("!requirements.txt", patched_content)
        self.assertIn("!app.py", patched_content)

    # ------------------------------------------------------------
    # 8. Valid and invalid Git repository URLs
    # ------------------------------------------------------------
    def test_case_8_valid_and_invalid_git_urls(self):
        # Valid URLs
        parsed1 = validate_git_url("https://github.com/my-org/my-repo.git")
        self.assertEqual(parsed1.owner, "my-org")
        self.assertEqual(parsed1.repo_name, "my-repo")

        parsed2 = validate_git_url("github.com/owner/project")
        self.assertEqual(parsed2.clone_url, "https://github.com/owner/project.git")

        # Invalid URLs
        with self.assertRaises(ValueError):
            validate_git_url("")

        # SSH URLs rejected with helpful message
        with self.assertRaises(ValueError) as ctx:
            validate_git_url("git@github.com:user/repo.git")
        self.assertIn("SSH Git URLs are not supported", str(ctx.exception))

        # Disallowed provider
        with self.assertRaises(ValueError) as ctx:
            validate_git_url("https://malicious-site.com/repo/app.git", allowed_providers=["github.com"])
        self.assertIn("not in allowed providers", str(ctx.exception))

    # ------------------------------------------------------------
    # 9. Git clone and authentication failures
    # ------------------------------------------------------------
    def test_case_9_git_clone_and_auth_failures(self):
        git_repo = GitRepository(self.temp_dir / "repos")

        with patch.object(git_repo, "_run_git") as mock_run_git:
            # Simulate authentication failure
            mock_run_git.side_effect = GitAuthenticationError("Git authentication failed: Invalid username or token")
            with self.assertRaises(GitAuthenticationError):
                git_repo.clone_or_fetch("https://github.com/private/repo.git", "repo-1", credential_token="bad_token")

            # Simulate network timeout / host resolution error
            mock_run_git.side_effect = GitNetworkError("Git network error: Could not resolve host")
            with self.assertRaises(GitNetworkError):
                git_repo.clone_or_fetch("https://bad-host.com/repo.git", "repo-2")

    # ------------------------------------------------------------
    # 10. Docker daemon unavailable
    # ------------------------------------------------------------
    def test_case_10_docker_daemon_unavailable(self):
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=1, stderr="Cannot connect to Docker daemon")
            self.assertFalse(is_docker_daemon_available())

            with self.assertRaises(RuntimeError) as ctx:
                ensure_jenkins_running()
            self.assertIn("Docker daemon is not running", str(ctx.exception))

    # ------------------------------------------------------------
    # 11. Jenkins unavailable or authentication failure
    # ------------------------------------------------------------
    def test_case_11_jenkins_unavailable_or_auth_failure(self):
        with patch("jenkins.Jenkins") as mock_cls:
            mock_cls.side_effect = Exception("HTTP 401: Unauthorized")
            server = jenkins_client.connect_to_jenkins("http://jenkins:8080", "bad_user", "bad_token")
            self.assertIsNone(server)

    # ------------------------------------------------------------
    # 12. Jenkins job creation/update and build failure
    # ------------------------------------------------------------
    def test_case_12_jenkins_job_and_build_failure(self):
        mock_server = MagicMock()
        mock_server.job_exists.return_value = False

        jenkins_client.create_job(mock_server, "test-job", "pipeline { agent any }")
        mock_server.create_job.assert_called_once()

        # Build failure reporting
        mock_server.get_build_info.return_value = {
            "building": False,
            "result": "FAILURE",
            "number": 5,
        }
        build_info = jenkins_client.wait_for_build_completion(mock_server, "test-job", 5, timeout=2, poll_interval=0.01)
        self.assertEqual(build_info["result"], "FAILURE")

    # ------------------------------------------------------------
    # 13. Deployment health-check failure
    # ------------------------------------------------------------
    def test_case_13_deployment_health_check_failure(self):
        async def _test():
            import database
            await database.init_db()
            mgr = DeploymentManager(health_check_timeout=1)
            with patch("deployment.manager.run_container", return_value="cid-123"), \
                 patch.object(mgr, "validate_candidate_health", return_value=(False, "Candidate failed health probe")), \
                 patch("deployment.manager.stop_and_remove_container"):
                res = await mgr.deploy_candidate(
                    repo_id="test-repo",
                    build_id="build-01",
                    image_tag="automator-test:latest",
                    container_port=5000,
                )
                self.assertFalse(res.success)
                self.assertIn("health probe", res.error_message)

        asyncio.run(_test())

    # ------------------------------------------------------------
    # 14. Missing or invalid configuration
    # ------------------------------------------------------------
    def test_case_14_missing_or_invalid_configuration(self):
        s = Settings()
        self.assertIsNotNone(s.BASE_DIR)
        self.assertTrue(s.PROJECTS_DIR.is_absolute())
        self.assertTrue(s.BUILDS_DIR.is_absolute())
        self.assertTrue(s.LOGS_DIR.is_absolute())
        self.assertTrue(s.REPOS_DIR.is_absolute())
        self.assertTrue(s.DB_PATH.is_absolute())


if __name__ == "__main__":
    unittest.main()
