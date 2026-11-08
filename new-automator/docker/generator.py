"""Automator Dockerfile Generation and Container Management Module.

Generates production-ready, multi-stage Dockerfiles with health checks,
non-root security, .dockerignore inspection, and manages isolated containers.
"""

from __future__ import annotations

import fnmatch
import json
import logging
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from jinja2 import Environment, FileSystemLoader

from analyzer.detector import DetectionResult, inspect_existing_dockerfile

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

DEFAULT_DOCKERIGNORE = """# Automator generated .dockerignore
.git
.gitignore
.dockerignore
.env
.env.*
*.env
*.pem
*.key
id_rsa*
__pycache__
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv/
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*
pnpm-debug.log*
.npm
target/
build/
.gradle/
.idea/
.vscode/
*.swp
.DS_Store
Thumbs.db
"""

# Critical build files that must never be excluded by .dockerignore
CRITICAL_BUILD_FILES: Set[str] = {
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "setup.py",
    "setup.cfg",
    "package.json",
    "package-lock.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "go.mod",
    "Dockerfile",
    "app.py",
    "main.py",
    "server.py",
}


# ============================================================
# DOCKERIGNORE INSPECTION & GENERATION
# ============================================================

def inspect_dockerignore(dockerignore_path: Path) -> List[str]:
    """Inspect .dockerignore and identify patterns that accidentally ignore critical build files."""
    if not dockerignore_path.exists():
        return []

    try:
        content = dockerignore_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        logger.warning("Failed to read %s: %s", dockerignore_path, exc)
        return []

    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
    conflicts: List[str] = []

    for critical in CRITICAL_BUILD_FILES:
        is_ignored = False
        for line in lines:
            if line.startswith("!"):
                if fnmatch.fnmatch(critical, line[1:]):
                    is_ignored = False
            else:
                if fnmatch.fnmatch(critical, line) or fnmatch.fnmatch(f"/{critical}", line):
                    is_ignored = True
        if is_ignored:
            conflicts.append(critical)

    return conflicts


def ensure_dockerignore(project_path: Path | str) -> Path:
    """Ensure a suitable .dockerignore file exists in the project root.

    Prevents required build files from being excluded.
    """
    path = Path(project_path).resolve()
    dockerignore_path = path / ".dockerignore"

    if not dockerignore_path.exists():
        dockerignore_path.write_text(DEFAULT_DOCKERIGNORE, encoding="utf-8")
        logger.info("Generated default .dockerignore at %s", dockerignore_path)
    else:
        # Check if existing .dockerignore excludes critical build files
        conflicts = inspect_dockerignore(dockerignore_path)
        if conflicts:
            logger.warning("Existing .dockerignore at %s excludes critical files: %s. Appending unignore rules.",
                           dockerignore_path, conflicts)
            try:
                unignore_rules = "\n\n# Automator safety overrides for required build files\n" + "\n".join(
                    f"!{f}" for f in conflicts
                ) + "\n"
                with open(dockerignore_path, "a", encoding="utf-8") as f:
                    f.write(unignore_rules)
            except Exception as exc:
                logger.warning("Could not patch .dockerignore: %s", exc)

    return dockerignore_path


# ============================================================
# COMMAND FORMATTING HELPER
# ============================================================

def format_exec_cmd(cmd_str: str) -> str:
    """Convert a command string into JSON exec array format for CMD.

    e.g. 'python app.py' -> '["python", "app.py"]'
    """
    if not cmd_str or not cmd_str.strip():
        return '["python", "app.py"]'

    clean = cmd_str.strip()
    if clean.startswith("[") and clean.endswith("]"):
        return clean

    try:
        parts = shlex.split(clean)
        return json.dumps(parts)
    except Exception:
        parts = clean.split()
        return json.dumps(parts)


# ============================================================
# PRE-BUILD PREREQUISITES VALIDATION
# ============================================================

def validate_build_prerequisites(project_path: Path, dockerfile_path: Path) -> None:
    """Validate that required files exist before executing docker build.

    Inspects Dockerfile COPY instructions and verifies source files exist
    and are not excluded by .dockerignore.

    Raises:
        FileNotFoundError: If project_path or dockerfile_path or copied files are missing.
        RuntimeError: If critical files are excluded.
    """
    if not project_path.exists() or not project_path.is_dir():
        raise FileNotFoundError(f"Docker build context directory does not exist: {project_path}")

    if not dockerfile_path.exists() or not dockerfile_path.is_file():
        raise FileNotFoundError(f"Dockerfile not found in build context: {dockerfile_path}")

    try:
        content = dockerfile_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        raise RuntimeError(f"Cannot read Dockerfile at {dockerfile_path}: {exc}")

    lines = content.splitlines()
    for line_num, line in enumerate(lines, 1):
        clean = line.strip()
        if not clean.upper().startswith("COPY "):
            continue

        parts = clean.split()
        if len(parts) < 3:
            continue

        # Skip COPY --from=... flags
        src_parts = [p for p in parts[1:-1] if not p.startswith("--")]
        for src in src_parts:
            # Skip wildcards, periods, and multi-stage copies
            if any(char in src for char in ["*", "?", "[", "]"]) or src == ".":
                continue

            src_file = (project_path / src).resolve()
            if not src_file.exists():
                raise FileNotFoundError(
                    f"Required build file '{src}' referenced in Dockerfile COPY instruction (line {line_num}) "
                    f"does not exist in build context: {project_path}. "
                    f"Verify project extraction and ensure required files are not missing."
                )

    # Check .dockerignore exclusions
    dockerignore_path = project_path / ".dockerignore"
    if dockerignore_path.exists():
        conflicts = inspect_dockerignore(dockerignore_path)
        if conflicts:
            # Ensure .dockerignore is patched to unignore them
            ensure_dockerignore(project_path)


# ============================================================
# DOCKERFILE GENERATOR
# ============================================================

def generate_dockerfile(
    project_path: Path | str,
    project_type_or_detection: Union[str, DetectionResult, Dict[str, Any]],
    force_regenerate: bool = False,
) -> Path:
    """Generate or validate a Dockerfile for the project.

    If an existing valid Dockerfile is present and force_regenerate is False,
    the existing Dockerfile is preserved and returned.

    Args:
        project_path: Project root directory.
        project_type_or_detection: Language string or DetectionResult object.
        force_regenerate: Overwrite existing Dockerfile if True.

    Returns:
        Path: Path to the generated or validated Dockerfile.
    """
    path = Path(project_path).resolve()
    dockerfile_path = path / "Dockerfile"

    # Always ensure .dockerignore is in place and verified
    ensure_dockerignore(path)

    # Convert detection to standard DetectionResult
    if isinstance(project_type_or_detection, DetectionResult):
        det = project_type_or_detection
    elif isinstance(project_type_or_detection, dict):
        det = DetectionResult(**project_type_or_detection)
    else:
        lang_str = str(project_type_or_detection).strip().lower()
        has_req = (path / "requirements.txt").exists()
        has_pyp = (path / "pyproject.toml").exists()
        dep_mgr = "pip" if has_req else ("pyproject" if has_pyp else "none")

        det = DetectionResult(
            language=lang_str,
            language_version="3.12" if "python" in lang_str else ("20" if "node" in lang_str else "21"),
            dependency_manager=dep_mgr,
            has_requirements_file=has_req,
            has_pyproject_file=has_pyp,
            dockerfile_template=lang_str,
            start_command="python app.py" if "python" in lang_str else ("npm start" if "node" in lang_str else "java -jar app.jar"),
            port=5000 if "python" in lang_str else (3000 if "node" in lang_str else 8080),
        )

    # Check existing Dockerfile
    if dockerfile_path.exists() and not force_regenerate:
        is_valid, issues, exposed_port, cmd = inspect_existing_dockerfile(dockerfile_path)
        if is_valid:
            logger.info("Using valid existing Dockerfile at %s", dockerfile_path)
            return dockerfile_path
        else:
            logger.warning("Existing Dockerfile has issues: %s. Regenerating.", issues)

    # Ensure has_requirements_file and has_pyproject_file reflect the actual filesystem
    has_req = (path / "requirements.txt").exists()
    has_pyp = (path / "pyproject.toml").exists()
    has_setup = (path / "setup.py").exists()

    template_name = det.dockerfile_template
    if template_name in ("python", "fastapi", "flask", "django"):
        template_file = "python.Dockerfile"
    elif template_name in ("node", "nodejs", "javascript", "typescript"):
        template_file = "node.Dockerfile"
    elif template_name in ("java-maven", "java-gradle", "java"):
        template_file = "java.Dockerfile"
    else:
        template_file = f"{template_name}.Dockerfile"

    context = {
        "language": det.language,
        "python_version": det.language_version or "3.12",
        "node_version": det.language_version or "20",
        "java_version": det.language_version or "21",
        "dependency_manager": det.dependency_manager,
        "has_requirements_file": has_req or det.has_requirements_file,
        "has_pyproject_file": has_pyp or det.has_pyproject_file,
        "has_setup_py": has_setup,
        "install_command": det.install_command or "npm install",
        "build_command": det.build_command,
        "start_command": det.start_command,
        "start_command_exec": format_exec_cmd(det.start_command),
        "port": det.port or 5000,
        "health_check_path": det.health_check_path or "/",
    }

    # Render Jinja2 template
    try:
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template(template_file)
        rendered_content = template.render(**context)
    except Exception as exc:
        logger.warning("Could not load Jinja2 template '%s': %s. Falling back to built-in generator.", template_file, exc)
        rendered_content = _builtin_fallback_dockerfile(det, context)

    dockerfile_path.write_text(rendered_content, encoding="utf-8")
    logger.info("Generated Dockerfile at %s for %s", dockerfile_path, det.language)
    return dockerfile_path


def _builtin_fallback_dockerfile(det: DetectionResult, context: Dict[str, Any]) -> str:
    """Built-in deterministic fallback generator if template file is missing."""
    lang = det.language
    port = context["port"]
    start_exec = context["start_command_exec"]
    health = context["health_check_path"]
    has_req = context.get("has_requirements_file", False)
    has_pyp = context.get("has_pyproject_file", False)
    dep_mgr = context.get("dependency_manager", "none")

    if "python" in lang:
        dep_section = ""
        if dep_mgr == "poetry":
            dep_section = """COPY pyproject.toml poetry.lock* ./
RUN pip install --no-cache-dir poetry && poetry config virtualenvs.create false && poetry install --no-root
"""
        elif dep_mgr == "pyproject" or (has_pyp and not has_req):
            dep_section = """COPY pyproject.toml ./
RUN pip install --no-cache-dir .
"""
        elif has_req or dep_mgr == "pip":
            dep_section = """COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
"""
        elif dep_mgr == "setup":
            dep_section = """COPY setup.py setup.cfg* ./
RUN pip install --no-cache-dir .
"""

        return f"""FROM python:{context['python_version']}-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT={port}
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
{dep_section}COPY . .
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE {port}
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \\
  CMD curl -f http://localhost:{port}{health} || exit 1
CMD {start_exec}
"""
    elif "node" in lang:
        return f"""FROM node:{context['node_version']}-slim AS builder
WORKDIR /app
COPY package*.json ./
RUN {context['install_command']}
COPY . .
FROM node:{context['node_version']}-slim AS runner
WORKDIR /app
ENV NODE_ENV=production PORT={port}
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app ./
RUN useradd -m -u 1000 nodeuser && chown -R nodeuser:nodeuser /app
USER nodeuser
EXPOSE {port}
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \\
  CMD curl -f http://localhost:{port}{health} || exit 1
CMD {start_exec}
"""
    elif "java" in lang:
        return f"""FROM maven:3.9-eclipse-temurin-{context['java_version']} AS builder
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn package -DskipTests -B
FROM eclipse-temurin:{context['java_version']}-jre-jammy AS runner
WORKDIR /app
ENV PORT={port}
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/target/*.jar app.jar
RUN useradd -m -u 1000 javauser && chown -R javauser:javauser /app
USER javauser
EXPOSE {port}
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=3 \\
  CMD curl -f http://localhost:{port}{health} || exit 1
CMD ["java", "-jar", "app.jar"]
"""
    else:
        raise ValueError(f"Unsupported project type for Dockerfile generation: {lang}")


# ============================================================
# DOCKER CLI OPERATIONS
# ============================================================

def build_image(
    project_path: Path | str,
    image_name: str,
    timeout: int = 600,
) -> str:
    """Build a Docker image from the project directory.

    Pre-validates required build files and build context prior to execution.

    Args:
        project_path: Path containing Dockerfile and source.
        image_name: Destination tag (e.g., 'automator-repo:build-1').
        timeout: Subprocess timeout in seconds.

    Returns:
        str: Created image tag name.

    Raises:
        FileNotFoundError: If project_path or required files are missing.
        RuntimeError: If image build fails or times out.
    """
    path = Path(project_path).resolve()
    dockerfile_path = path / "Dockerfile"

    # Pre-build validation: verify build context and files referenced in COPY instructions
    validate_build_prerequisites(path, dockerfile_path)

    cmd = ["docker", "build", "-t", image_name, str(path)]

    logger.info("Building Docker image %s from %s", image_name, path)
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Docker build timed out after {timeout}s for {image_name}") from exc
    except OSError as exc:
        raise RuntimeError(f"Failed to execute Docker build: {exc}") from exc

    if res.returncode != 0:
        logger.error("Docker build failed:\nStdout: %s\nStderr: %s", res.stdout, res.stderr)
        raise RuntimeError(f"Docker image build failed for {image_name}:\n{res.stderr.strip()}")

    logger.info("Docker image %s built successfully", image_name)
    return image_name


def run_container(
    image_name: str,
    container_name: str,
    host_port: int,
    container_port: int,
    env_vars: Optional[Dict[str, str]] = None,
    network: Optional[str] = None,
) -> str:
    """Start a Docker container.

    Args:
        image_name: Tag of the image to run.
        container_name: Target container name.
        host_port: Host port mapping.
        container_port: Container listening port.
        env_vars: Optional environment key-value pairs.
        network: Optional Docker network.

    Returns:
        str: Container ID.

    Raises:
        RuntimeError: If container fails to start.
    """
    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "-p", f"{host_port}:{container_port}",
    ]

    if network:
        cmd.extend(["--network", network])

    if env_vars:
        for k, v in env_vars.items():
            cmd.extend(["-e", f"{k}={v}"])

    cmd.append(image_name)

    logger.info("Running Docker container %s (host port %d)", container_name, host_port)
    res = subprocess.run(cmd, capture_output=True, text=True)

    if res.returncode != 0:
        logger.error("Docker container start failed: %s", res.stderr)
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True)
        raise RuntimeError(f"Docker container {container_name} failed to start: {res.stderr.strip()}")

    container_id = res.stdout.strip()
    return container_id


def stop_and_remove_container(container_name: str, timeout: int = 10) -> bool:
    """Safely stop and remove a container.

    Returns:
        bool: True if stopped and removed successfully or container didn't exist.
    """
    try:
        subprocess.run(["docker", "stop", "-t", str(timeout), container_name], capture_output=True, text=True)
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True)
        return True
    except Exception as exc:
        logger.warning("Error stopping container %s: %s", container_name, exc)
        return False
