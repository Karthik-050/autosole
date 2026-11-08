import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

DOCKER_TEMPLATES = {
    "python": """FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
""",

    "node": """FROM node:22-slim

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "start"]
""",

    "java": """FROM maven:3.9-eclipse-temurin-21

WORKDIR /app

COPY pom.xml .

RUN mvn dependency:go-offline

COPY . .

RUN mvn package -DskipTests

CMD ["java", "-jar", "target/app.jar"]
""",

    "java-maven": """FROM maven:3.9-eclipse-temurin-21

WORKDIR /app

COPY pom.xml .

RUN mvn dependency:go-offline

COPY . .

RUN mvn package -DskipTests

CMD ["java", "-jar", "target/app.jar"]
""",

    "java-gradle": """FROM gradle:8-jdk21

WORKDIR /app

COPY . .

RUN gradle build -x test

CMD ["java", "-jar", "build/libs/app.jar"]
"""
}

class DockerManager:
    def __init__(self):
        self.cli_available = shutil.which("docker") is not None

    def get_status(self) -> Dict[str, Any]:
        """Check if Docker CLI is installed and daemon is responsive."""
        if not self.cli_available:
            return {
                "available": False,
                "status": "not_installed",
                "version": None,
                "error": "Docker CLI is not installed or not in PATH.",
            }

        try:
            res = subprocess.run(
                ["docker", "info", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                try:
                    info = json.loads(res.stdout)
                    return {
                        "available": True,
                        "status": "running",
                        "server_version": info.get("ServerVersion", "Unknown"),
                        "containers_running": info.get("ContainersRunning", 0),
                        "containers_total": info.get("Containers", 0),
                        "images_count": info.get("Images", 0),
                        "os": info.get("OperatingSystem", "Unknown"),
                        "error": None,
                    }
                except Exception:
                    return {
                        "available": True,
                        "status": "running",
                        "server_version": "Connected",
                        "containers_running": 0,
                        "containers_total": 0,
                        "images_count": 0,
                        "error": None,
                    }
            else:
                return {
                    "available": False,
                    "status": "daemon_stopped",
                    "server_version": None,
                    "error": res.stderr.strip() or "Docker daemon is not running. Please start Docker Desktop.",
                }
        except subprocess.TimeoutExpired:
            return {
                "available": False,
                "status": "timeout",
                "server_version": None,
                "error": "Docker daemon connection timed out.",
            }
        except Exception as e:
            return {
                "available": False,
                "status": "error",
                "server_version": None,
                "error": str(e),
            }

    def generate_dockerfile(self, project_path: Path, project_type: str = "python") -> Path:
        """Generates or updates Dockerfile in the project directory."""
        project_path = Path(project_path)
        if not project_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {project_path}")

        template = DOCKER_TEMPLATES.get(project_type, DOCKER_TEMPLATES["python"])
        dockerfile_path = project_path / "Dockerfile"
        dockerfile_path.write_text(template, encoding="utf-8")
        return dockerfile_path

    def get_dockerfile(self, project_path: Path) -> Optional[str]:
        df = Path(project_path) / "Dockerfile"
        if df.is_file():
            return df.read_text(encoding="utf-8", errors="replace")
        return None

    def save_dockerfile(self, project_path: Path, content: str):
        df = Path(project_path) / "Dockerfile"
        df.write_text(content, encoding="utf-8")

    def build_image(self, project_path: Path, image_name: str) -> Dict[str, Any]:
        """Builds Docker image and returns structured result with logs."""
        status = self.get_status()
        if not status["available"]:
            raise RuntimeError(f"Docker is unavailable: {status['error']}")

        cmd = ["docker", "build", "-t", image_name, str(project_path)]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "success": res.returncode == 0,
                "image_name": image_name,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "image_name": image_name,
                "stdout": "",
                "stderr": "Build timed out after 300 seconds",
                "exit_code": -1,
            }
        except Exception as e:
            return {
                "success": False,
                "image_name": image_name,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
            }

    def list_images(self) -> List[Dict[str, Any]]:
        status = self.get_status()
        if not status["available"]:
            return []

        try:
            res = subprocess.run(
                ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedAt}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode != 0:
                return []

            images = []
            for line in res.stdout.splitlines():
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    images.append({
                        "tag": parts[0],
                        "id": parts[1],
                        "size": parts[2],
                        "created": parts[3] if len(parts) > 3 else "",
                    })
            return images
        except Exception:
            return []

    def list_containers(self) -> List[Dict[str, Any]]:
        status = self.get_status()
        if not status["available"]:
            return []

        try:
            res = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode != 0:
                return []

            containers = []
            for line in res.stdout.splitlines():
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 4:
                    containers.append({
                        "id": parts[0],
                        "name": parts[1],
                        "image": parts[2],
                        "status": parts[3],
                        "ports": parts[4] if len(parts) > 4 else "",
                        "running": "Up" in parts[3],
                    })
            return containers
        except Exception:
            return []

    def run_container(self, image_name: str, container_name: str, host_port: int, container_port: int = 5000) -> Dict[str, Any]:
        status = self.get_status()
        if not status["available"]:
            raise RuntimeError(f"Docker is unavailable: {status['error']}")

        # Remove existing container with same name if present
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True)

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "-p", f"{host_port}:{container_port}",
            image_name,
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            return {
                "success": False,
                "error": res.stderr.strip() or "Container failed to start",
                "container_id": None,
            }

        return {
            "success": True,
            "container_id": res.stdout.strip(),
            "container_name": container_name,
            "port": host_port,
        }

    def stop_container(self, container_name_or_id: str) -> Dict[str, Any]:
        res = subprocess.run(["docker", "stop", container_name_or_id], capture_output=True, text=True)
        return {"success": res.returncode == 0, "output": res.stdout.strip() or res.stderr.strip()}

    def remove_container(self, container_name_or_id: str) -> Dict[str, Any]:
        res = subprocess.run(["docker", "rm", "-f", container_name_or_id], capture_output=True, text=True)
        return {"success": res.returncode == 0, "output": res.stdout.strip() or res.stderr.strip()}
