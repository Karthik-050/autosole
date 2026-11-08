"""Automated tests for Jenkins pipeline generation and client operations."""

import unittest
from unittest.mock import MagicMock, patch

from analyzer.detector import DetectionResult
from jenkins_automation import client as jenkins_client
from jenkins_automation.job_generator import generate_pipeline, sanitize_name


class TestJenkinsPipelineGenerator(unittest.TestCase):
    """Test dynamic Jenkins Declarative Pipeline script generation."""

    def test_sanitize_name(self):
        self.assertEqual(sanitize_name("My Super App!"), "my-super-app")
        self.assertEqual(sanitize_name("foo---bar"), "foo-bar")
        self.assertEqual(sanitize_name(""), "project")

    def test_generate_python_pipeline(self):
        det = DetectionResult(
            language="python",
            language_version="3.12",
            test_command="pytest -v",
            port=8000,
            health_check_path="/health",
        )

        pipeline = generate_pipeline(
            project_name="api-service",
            image_name="automator-api:build-1",
            container_name="automator-api",
            container_port=8000,
            detection_result=det,
            workspace_rel_path="workspaces/repo-1/b-1",
        )

        self.assertIn("pipeline {", pipeline)
        self.assertIn("stage('Source & Workspace Validation')", pipeline)
        self.assertIn("stage('Static Analysis & Linting')", pipeline)
        self.assertIn("stage('Automated Tests')", pipeline)
        self.assertIn("pytest -v", pipeline)
        self.assertIn("stage('Build Docker Image')", pipeline)
        self.assertIn("stage('Isolated Candidate Container Validation')", pipeline)
        self.assertIn("automator-api-candidate", pipeline)
        self.assertIn("docker rm -f", pipeline)

    def test_generate_node_pipeline(self):
        det = DetectionResult(
            language="node",
            language_version="20",
            build_command="npm run build",
            test_command="npm test",
            port=3000,
        )

        pipeline = generate_pipeline(
            project_name="web-frontend",
            image_name="automator-web:build-1",
            container_name="automator-web",
            detection_result=det,
        )

        self.assertIn("npm run build", pipeline)
        self.assertIn("npm test", pipeline)
        self.assertIn("stage('Project Build')", pipeline)

    def test_generate_python_pipeline_skips_tests_when_none_detected(self):
        pipeline = generate_pipeline(
            project_name="no-tests-app",
            image_name="automator-no-tests:build-1",
            container_name="automator-no-tests",
            detection_result=DetectionResult(language="python", language_version="3.12"),
            workspace_rel_path="workspaces/repo-1/build-1",
        )

        self.assertIn("No automated tests detected; skipping.", pipeline)
        self.assertNotIn("python -m unittest discover", pipeline)
        self.assertIn("python3 -m compileall -q .", pipeline)
        self.assertNotIn("compileall -q . 2>/dev/null || true", pipeline)
        self.assertIn("CANDIDATE_PORT = '5003'", pipeline)


class TestJenkinsClient(unittest.TestCase):
    """Test Jenkins API client operations with mocked Jenkins server."""

    def test_connect_to_jenkins_failure(self):
        with patch("jenkins.Jenkins") as mock_jenkins_cls:
            mock_jenkins_cls.side_effect = Exception("Connection refused")
            server = jenkins_client.connect_to_jenkins("http://bad-jenkins:8080", "admin", "token")
            self.assertIsNone(server)

    def test_create_or_update_job(self):
        mock_server = MagicMock()
        mock_server.job_exists.return_value = False

        jenkins_client.create_job(mock_server, "my-job", "pipeline { agent any }")
        mock_server.create_job.assert_called_once()

        # Update existing
        mock_server.job_exists.return_value = True
        jenkins_client.create_job(mock_server, "my-job", "pipeline { agent any }")
        mock_server.reconfig_job.assert_called_once()

    def test_trigger_job(self):
        mock_server = MagicMock()
        mock_server.build_job.return_value = 101

        qid = jenkins_client.trigger_job(mock_server, "my-job")
        self.assertEqual(qid, 101)

    def test_get_build_from_queue(self):
        mock_server = MagicMock()
        mock_server.get_queue_item.return_value = {
            "executable": {"number": 42}
        }

        build_num = jenkins_client.get_build_from_queue(mock_server, 101, timeout=5)
        self.assertEqual(build_num, 42)

    def test_wait_for_build_completion(self):
        mock_server = MagicMock()
        mock_server.get_build_info.side_effect = [
            {"building": True, "number": 42},
            {"building": False, "result": "SUCCESS", "number": 42},
        ]

        info = jenkins_client.wait_for_build_completion(mock_server, "my-job", 42, timeout=10, poll_interval=0.01)
        self.assertIsNotNone(info)
        self.assertEqual(info["result"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
