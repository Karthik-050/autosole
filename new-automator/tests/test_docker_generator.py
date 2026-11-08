"""Automated tests for Dockerfile generation, .dockerignore security, and templates."""

from pathlib import Path
import shutil
import tempfile
import unittest

from analyzer.detector import DetectionResult
from docker.generator import (
    DEFAULT_DOCKERIGNORE,
    ensure_dockerignore,
    format_exec_cmd,
    generate_dockerfile,
)


class TestDockerGenerator(unittest.TestCase):
    """Test Dockerfile generation, template rendering, and .dockerignore validation."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_dockerignore_generation(self):
        ensure_dockerignore(self.temp_dir)
        ign_path = self.temp_dir / ".dockerignore"
        self.assertTrue(ign_path.exists())

        content = ign_path.read_text(encoding="utf-8")
        self.assertIn(".git", content)
        self.assertIn(".env", content)
        self.assertIn("node_modules/", content)
        self.assertIn("venv/", content)
        self.assertIn("id_rsa*", content)

    def test_format_exec_cmd(self):
        self.assertEqual(format_exec_cmd('python app.py'), '["python", "app.py"]')
        self.assertEqual(format_exec_cmd('uvicorn main:app --port 8000'), '["uvicorn", "main:app", "--port", "8000"]')
        # Already formatted JSON
        self.assertEqual(format_exec_cmd('["python", "app.py"]'), '["python", "app.py"]')

    def test_generate_python_dockerfile(self):
        det = DetectionResult(
            language="python",
            language_version="3.12",
            framework="fastapi",
            start_command="uvicorn main:app --host 0.0.0.0 --port 8000",
            port=8000,
            health_check_path="/health",
            dockerfile_template="python",
        )

        df_path = generate_dockerfile(self.temp_dir, det)
        self.assertTrue(df_path.exists())

        content = df_path.read_text(encoding="utf-8")
        self.assertIn("FROM python:3.12-slim", content)
        self.assertIn("EXPOSE 8000", content)
        self.assertIn("HEALTHCHECK", content)
        self.assertIn("useradd", content)  # Non-root user
        self.assertIn('CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]', content)

    def test_generate_node_dockerfile(self):
        det = DetectionResult(
            language="node",
            language_version="20",
            framework="express",
            start_command="npm start",
            port=3000,
            health_check_path="/",
            dockerfile_template="node",
        )

        df_path = generate_dockerfile(self.temp_dir, det)
        content = df_path.read_text(encoding="utf-8")
        self.assertIn("FROM node:20-slim", content)
        self.assertIn("EXPOSE 3000", content)
        self.assertIn("AS builder", content)  # Multi-stage build
        self.assertIn("AS runner", content)

    def test_generate_java_maven_dockerfile(self):
        det = DetectionResult(
            language="java-maven",
            language_version="21",
            framework="spring-boot",
            start_command="java -jar app.jar",
            port=8080,
            dockerfile_template="java-maven",
        )

        df_path = generate_dockerfile(self.temp_dir, det)
        content = df_path.read_text(encoding="utf-8")
        self.assertIn("FROM maven:3.9-eclipse-temurin-21", content)
        self.assertIn("FROM eclipse-temurin:21-jre-jammy", content)
        self.assertIn("EXPOSE 8080", content)

    def test_preserve_valid_user_dockerfile(self):
        user_dockerfile = self.temp_dir / "Dockerfile"
        original_content = "FROM alpine:3.18\nWORKDIR /app\nEXPOSE 7000\nCMD [\"echo\", \"custom\"]\n"
        user_dockerfile.write_text(original_content, encoding="utf-8")

        det = DetectionResult(
            language="python",
            language_version="3.12",
            has_existing_dockerfile=True,
            existing_dockerfile_valid=True,
        )

        # Do not force regenerate
        df_path = generate_dockerfile(self.temp_dir, det, force_regenerate=False)
        self.assertEqual(df_path.read_text(encoding="utf-8"), original_content)

        # Force regenerate
        df_path_regen = generate_dockerfile(self.temp_dir, det, force_regenerate=True)
        self.assertNotEqual(df_path_regen.read_text(encoding="utf-8"), original_content)
        self.assertIn("FROM python", df_path_regen.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
