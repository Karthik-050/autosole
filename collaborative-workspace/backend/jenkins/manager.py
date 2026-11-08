import time
import json
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional
from backend.config import settings

try:
    import jenkins
except ImportError:
    jenkins = None

def sanitize_name(name: str) -> str:
    """Convert project name into a Docker/Jenkins-safe name."""
    name = name.lower()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
    clean = "".join(char if char in allowed else "-" for char in name)
    while "--" in clean:
        clean = clean.replace("--", "-")
    return clean.strip("-")

def generate_pipeline(project_name: str, image_name: str, container_name: str, container_port: int = 5000) -> str:
    """Generate Declarative Jenkins Pipeline script."""
    safe_name = sanitize_name(project_name)
    return f"""pipeline {{
    agent any

    stages {{
        stage('Check Project') {{
            steps {{
                echo "================================"
                echo "Checking Project: {safe_name}"
                echo "================================"
            }}
        }}

        stage('Build Docker Image') {{
            steps {{
                echo "================================"
                echo "Building Docker Image: {image_name}"
                echo "================================"
                sh "docker build -t {image_name} ."
            }}
        }}

        stage('Run Container') {{
            steps {{
                echo "================================"
                echo "Deploying Container: {container_name}"
                echo "================================"
                sh "docker rm -f {container_name} 2>/dev/null || true"
                sh "docker run -d --name {container_name} -p 5001:{container_port} {image_name}"
            }}
        }}

        stage('Health Check') {{
            steps {{
                echo "================================"
                echo "Verifying Health Check..."
                echo "================================"
                sleep 5
                sh "curl -f http://localhost:5001/ || true"
                echo "Deployment Verification Finished."
            }}
        }}
    }}
}}"""

def generate_repository_pipeline(
    project_id: str,
    repository_url: str,
    branch: str,
    project_type: str,
    entrypoint: Optional[str] = None,
    container_port: int = 5000,
    credentials_id: str = "",
) -> str:
    """Render the Jenkinsfile used for GitHub-triggered blue-green deployment."""
    slug = sanitize_name(project_id)
    if not slug:
        raise ValueError("Project ID must contain letters or digits")
    if not (1 <= container_port <= 65535):
        raise ValueError("Container port must be between 1 and 65535")

    def groovy_string(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("'", "\\'").replace("$", "\\$")
        escaped = escaped.replace("\r", "\\r").replace("\n", "\\n")
        return f"'{escaped}'"

    template = Path(__file__).with_name("repository_pipeline.groovy").read_text(encoding="utf-8")
    replacements = {
        "@@PROJECT_SLUG@@": groovy_string(slug),
        "@@REPOSITORY_URL@@": groovy_string(repository_url),
        "@@SOURCE_BRANCH@@": groovy_string(branch),
        "@@CREDENTIALS_ID@@": groovy_string(credentials_id),
        "@@CONTAINER_PORT@@": str(container_port),
        "@@DOCKERFILE_TEXT@@": json.dumps(_fallback_dockerfile(project_type, entrypoint, container_port)).replace("$", "\\$"),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def _fallback_dockerfile(project_type: str, entrypoint: Optional[str], container_port: int) -> str:
    if project_type == "python":
        command = json.dumps(["python", entrypoint or "app.py"])
        return (
            "FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\n"
            "RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi\n"
            f"EXPOSE {container_port}\nCMD {command}\n"
        )
    if project_type == "node":
        return (
            "FROM node:22-slim\nWORKDIR /app\nCOPY package*.json ./\n"
            "RUN npm install\nCOPY . .\n"
            f"EXPOSE {container_port}\nCMD [\"npm\", \"start\"]\n"
        )
    return ""


class JenkinsManager:
    def __init__(self):
        pass

    def _get_server(self):
        if jenkins is None:
            raise RuntimeError("python-jenkins package is not installed")
        if not settings.jenkins_api_token:
            # Anonymous or token-less check
            return jenkins.Jenkins(settings.jenkins_url, timeout=5)
        return jenkins.Jenkins(
            settings.jenkins_url,
            username=settings.jenkins_username,
            password=settings.jenkins_api_token,
            timeout=5,
        )

    def get_status(self) -> Dict[str, Any]:
        """Check if Jenkins server is reachable."""
        try:
            # Fast ping first via requests
            resp = requests.get(settings.jenkins_url, timeout=3)
            # Check version header
            version = resp.headers.get("X-Jenkins", "Unknown")

            # Try authenticated info if possible
            server = self._get_server()
            user_info = None
            try:
                user_info = server.get_whoami()
            except Exception:
                pass

            return {
                "available": True,
                "status": "online",
                "url": settings.jenkins_url,
                "version": version,
                "user": user_info["fullName"] if user_info else settings.jenkins_username,
                "error": None,
            }
        except requests.exceptions.RequestException as e:
            return {
                "available": False,
                "status": "offline",
                "url": settings.jenkins_url,
                "version": None,
                "user": None,
                "error": f"Cannot connect to Jenkins at {settings.jenkins_url}. Make sure Jenkins is running.",
            }
        except Exception as e:
            return {
                "available": False,
                "status": "offline",
                "url": settings.jenkins_url,
                "version": None,
                "user": None,
                "error": str(e),
            }

    def list_jobs(self) -> List[Dict[str, Any]]:
        status = self.get_status()
        if not status["available"]:
            return []

        try:
            server = self._get_server()
            return server.get_jobs()
        except Exception:
            return []

    def create_or_update_job(self, job_name: str, pipeline_script: str) -> Dict[str, Any]:
        status = self.get_status()
        if not status["available"]:
            raise RuntimeError(f"Jenkins is offline: {status['error']}")

        server = self._get_server()
        safe_pipeline_script = pipeline_script.replace("]]>", "]" * 4 + "><![CDATA[>")
        job_config = f"""<flow-definition plugin="workflow-job">
    <description>Automator generated Jenkins pipeline</description>
    <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition">
        <script><![CDATA[
{safe_pipeline_script}
        ]]></script>
        <sandbox>true</sandbox>
    </definition>
    <triggers/>
</flow-definition>"""

        if not server.job_exists(job_name):
            server.create_job(job_name, job_config)
            action = "created"
        else:
            server.reconfig_job(job_name, job_config)
            action = "updated"

        return {"success": True, "action": action, "job_name": job_name}

    def create_or_update_repository_job(
        self,
        project_id: str,
        repository_url: str,
        branch: str,
        project_type: str,
        entrypoint: Optional[str],
        container_port: int,
    ) -> Dict[str, Any]:
        slug = sanitize_name(project_id)
        job_name = f"project-k-{slug}"
        script = generate_repository_pipeline(
            project_id=project_id,
            repository_url=repository_url,
            branch=branch,
            project_type=project_type,
            entrypoint=entrypoint,
            container_port=container_port,
            credentials_id=settings.github_jenkins_credential_id,
        )
        result = self.create_or_update_job(job_name, script)
        return {**result, "pipeline_script": script}

    def trigger_build(self, job_name: str) -> Dict[str, Any]:
        status = self.get_status()
        if not status["available"]:
            raise RuntimeError(f"Jenkins is offline: {status['error']}")

        server = self._get_server()
        queue_id = server.build_job(job_name)
        return {
            "success": True,
            "job_name": job_name,
            "queue_id": queue_id,
        }

    def get_build_status(self, job_name: str, build_number: Optional[int] = None) -> Optional[Dict[str, Any]]:
        status = self.get_status()
        if not status["available"]:
            return None

        try:
            server = self._get_server()
            if not server.job_exists(job_name):
                return None

            job_info = server.get_job_info(job_name)
            last_build = job_info.get("lastBuild")
            if not last_build:
                return {
                    "job_name": job_name,
                    "has_builds": False,
                    "status": "NO_BUILDS",
                }

            b_num = build_number or last_build["number"]
            build_info = server.get_build_info(job_name, b_num)

            result = build_info.get("result")
            is_building = build_info.get("building", False)

            computed_status = "RUNNING" if is_building else (result or "QUEUED")

            return {
                "job_name": job_name,
                "has_builds": True,
                "build_number": b_num,
                "status": computed_status,
                "result": result,
                "duration_ms": build_info.get("duration", 0),
                "timestamp": build_info.get("timestamp", 0),
                "url": build_info.get("url", ""),
            }
        except Exception:
            return None

    def get_build_console(self, job_name: str, build_number: int) -> str:
        status = self.get_status()
        if not status["available"]:
            return "Jenkins is offline."

        try:
            server = self._get_server()
            return server.get_build_console_output(job_name, build_number)
        except Exception as e:
            return f"Error retrieving console logs: {e}"
