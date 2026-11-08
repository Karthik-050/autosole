"""Automated tests for stack analyzer, framework detection, and monorepos."""

from pathlib import Path
import shutil
import tempfile
import unittest

from analyzer.detector import (
    DetectionResult,
    detect_project,
    discover_subprojects,
    inspect_existing_dockerfile,
)


class TestProjectAnalyzer(unittest.TestCase):
    """Test automatic stack detection across different technology ecosystems."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_detect_python_fastapi(self):
        project = self.temp_dir / "fastapi_app"
        project.mkdir()
        (project / "requirements.txt").write_text("fastapi>=0.100.0\nuvicorn>=0.20.0\n", encoding="utf-8")
        (project / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

        res = detect_project(project)
        self.assertEqual(res.language, "python")
        self.assertEqual(res.framework, "fastapi")
        self.assertEqual(res.port, 8000)
        self.assertIn("uvicorn", res.start_command)
        self.assertEqual(res.dockerfile_template, "python")
        self.assertTrue(res.confidence >= 0.9)

    def test_detect_python_flask(self):
        project = self.temp_dir / "flask_app"
        project.mkdir()
        (project / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
        (project / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")

        res = detect_project(project)
        self.assertEqual(res.language, "python")
        self.assertEqual(res.framework, "flask")
        self.assertEqual(res.port, 5000)
        self.assertIn("python app.py", res.start_command)
        self.assertIsNone(res.test_command)

    def test_python_test_command_requires_test_files(self):
        project = self.temp_dir / "python_app"
        project.mkdir()
        (project / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
        (project / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")

        self.assertIsNone(detect_project(project).test_command)

        tests_dir = project / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_app.py").write_text("import unittest\n", encoding="utf-8")
        self.assertEqual(detect_project(project).test_command, "python -m unittest discover")

    def test_detect_node_express(self):
        project = self.temp_dir / "node_app"
        project.mkdir()
        (project / "package.json").write_text(
            '{"name": "my-express", "scripts": {"start": "node server.js", "test": "jest"}, "dependencies": {"express": "^4.18.2"}}',
            encoding="utf-8",
        )
        (project / "package-lock.json").write_text("{}", encoding="utf-8")
        (project / "server.js").write_text("const express = require('express');", encoding="utf-8")

        res = detect_project(project)
        self.assertEqual(res.language, "node")
        self.assertEqual(res.framework, "express")
        self.assertEqual(res.dependency_manager, "npm")
        self.assertEqual(res.install_command, "npm ci")
        self.assertEqual(res.start_command, "npm start")
        self.assertEqual(res.test_command, "npm test")
        self.assertEqual(res.port, 3000)

    def test_detect_java_maven(self):
        project = self.temp_dir / "maven_app"
        project.mkdir()
        (project / "pom.xml").write_text(
            """<project>
                <modelVersion>4.0.0</modelVersion>
                <groupId>com.example</groupId>
                <artifactId>demo</artifactId>
                <version>0.0.1-SNAPSHOT</version>
                <properties><java.version>21</java.version></properties>
                <dependencies>
                    <dependency>
                        <groupId>org.springframework.boot</groupId>
                        <artifactId>spring-boot-starter-web</artifactId>
                    </dependency>
                </dependencies>
            </project>""",
            encoding="utf-8",
        )

        res = detect_project(project)
        self.assertEqual(res.language, "java-maven")
        self.assertEqual(res.language_version, "21")
        self.assertEqual(res.framework, "spring-boot")
        self.assertEqual(res.dependency_manager, "maven")
        self.assertEqual(res.port, 8080)
        self.assertIn("mvn", res.build_command)

    def test_detect_java_gradle(self):
        project = self.temp_dir / "gradle_app"
        project.mkdir()
        (project / "build.gradle").write_text(
            "plugins { id 'org.springframework.boot' version '3.2.0' }\njava { sourceCompatibility = '17' }",
            encoding="utf-8",
        )

        res = detect_project(project)
        self.assertEqual(res.language, "java-gradle")
        self.assertEqual(res.dependency_manager, "gradle")
        self.assertIn("gradle", res.build_command)

    def test_detect_go(self):
        project = self.temp_dir / "go_app"
        project.mkdir()
        (project / "go.mod").write_text("module example.com/myapp\n\ngo 1.22\n", encoding="utf-8")
        (project / "main.go").write_text("package main\nfunc main() {}", encoding="utf-8")

        res = detect_project(project)
        self.assertEqual(res.language, "go")
        self.assertEqual(res.language_version, "1.22")
        self.assertEqual(res.build_command, "go build -o /app/server .")

    def test_unknown_project(self):
        project = self.temp_dir / "empty_dir"
        project.mkdir()
        (project / "notes.txt").write_text("hello", encoding="utf-8")

        res = detect_project(project)
        self.assertEqual(res.language, "unknown")
        self.assertEqual(res.confidence, 0.0)

    def test_monorepository_discovery(self):
        monorepo = self.temp_dir / "monorepo"
        monorepo.mkdir()

        # Service A: Python
        svc_a = monorepo / "services" / "api"
        svc_a.mkdir(parents=True)
        (svc_a / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

        # Service B: Node
        svc_b = monorepo / "services" / "web"
        svc_b.mkdir(parents=True)
        (svc_b / "package.json").write_text('{"name": "web", "dependencies": {"next": "14"}}', encoding="utf-8")

        subprojects = discover_subprojects(monorepo)
        self.assertEqual(len(subprojects), 2)
        roots = {s["project_root"] for s in subprojects}
        self.assertIn("services/api", roots)
        self.assertIn("services/web", roots)

        # Monorepo root detection
        res = detect_project(monorepo)
        self.assertEqual(res.application_type, "monorepo")
        self.assertEqual(len(res.subprojects), 2)

    def test_existing_dockerfile_inspection(self):
        project = self.temp_dir / "custom_docker"
        project.mkdir()
        (project / "requirements.txt").write_text("flask\n", encoding="utf-8")

        # Valid custom Dockerfile
        valid_df = project / "Dockerfile"
        valid_df.write_text("FROM python:3.11-alpine\nWORKDIR /app\nCOPY . .\nEXPOSE 9000\nCMD [\"python\", \"app.py\"]\n")

        is_valid, issues, port, cmd = inspect_existing_dockerfile(valid_df)
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
        self.assertEqual(port, 9000)
        self.assertIn("python", cmd)

        # Invalidate with sensitive file copy
        bad_df = project / "Dockerfile.bad"
        bad_df.write_text("FROM python:3.11\nCOPY .env /app/.env\nCMD [\"python\", \"app.py\"]\n")
        is_bad_valid, bad_issues, _, _ = inspect_existing_dockerfile(bad_df)
        self.assertFalse(is_bad_valid)
        self.assertTrue(any(".env" in iss for iss in bad_issues))


if __name__ == "__main__":
    unittest.main()
