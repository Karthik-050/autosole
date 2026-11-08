"""Automator Project Technology Stack and Build Strategy Analyzer.

Inspects repository contents, metadata, lockfiles, and configuration
to determine language, framework, dependencies, build/test commands,
ports, health check endpoints, and Dockerfile generation strategies.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
import tomllib
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# STRUCTURED DETECTION RESULT
# ============================================================

@dataclass
class DetectionResult:
    """Comprehensive technology stack and build analysis output."""

    language: str                                # "python", "node", "java-maven", "java-gradle", "go", "unknown"
    language_version: str                        # e.g., "3.12", "20", "21", "1.22"
    framework: Optional[str] = None              # "fastapi", "flask", "django", "express", "spring-boot", etc.
    application_type: str = "web-api"            # "web-api", "web-app", "cli", "worker", "monorepo"
    project_root: str = "."                      # Project root or relative subproject directory
    dependency_manager: str = "unknown"          # "pip", "poetry", "pyproject", "pipenv", "setup", "none", "npm", "maven", "gradle", "go"
    has_requirements_file: bool = False          # True if requirements.txt exists at root
    has_pyproject_file: bool = False             # True if pyproject.toml exists at root
    install_command: str = ""                    # e.g., "pip install -r requirements.txt"
    build_command: Optional[str] = None          # e.g., "npm run build" or "mvn package -DskipTests"
    test_command: Optional[str] = None           # e.g., "pytest" or "npm test"
    start_command: str = ""                      # e.g., "python app.py"
    port: int = 5000                             # Listening network port
    health_check_path: str = "/health"           # HTTP endpoint or probe
    dockerfile_template: str = "unknown"         # Key for Dockerfile template
    has_existing_dockerfile: bool = False        # User-supplied Dockerfile exists
    existing_dockerfile_valid: bool = False      # Existing Dockerfile passed basic validation
    existing_dockerfile_issues: List[str] = field(default_factory=list)
    confidence: float = 0.0                      # Confidence score 0.0 to 1.0
    warnings: List[str] = field(default_factory=list)
    subprojects: List[Dict[str, Any]] = field(default_factory=list)

    def __str__(self) -> str:
        """Allow backward-compatible string comparison with legacy code.

        Legacy code expects `detect_project(...)` to return "python", "node", etc.
        """
        return self.dockerfile_template if self.dockerfile_template != "unknown" else self.language

    def __eq__(self, other: Any) -> bool:
        """Allow comparison with string values for backward compatibility."""
        if isinstance(other, str):
            return str(self) == other or self.language == other or self.dockerfile_template == other
        return super().__eq__(other)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to a serializable dictionary."""
        return asdict(self)


# ============================================================
# DOCKERFILE VALIDATOR
# ============================================================

def inspect_existing_dockerfile(dockerfile_path: Path) -> Tuple[bool, List[str], Optional[int], Optional[str]]:
    """Inspect and validate a user-supplied Dockerfile.

    Returns:
        (is_valid, issues, exposed_port, cmd)
    """
    if not dockerfile_path.exists() or not dockerfile_path.is_file():
        return False, ["Dockerfile does not exist"], None, None

    issues: List[str] = []
    has_from = False
    has_cmd_or_entrypoint = False
    exposed_port: Optional[int] = None
    cmd_or_entrypoint: Optional[str] = None

    try:
        content = dockerfile_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return False, [f"Failed to read Dockerfile: {exc}"], None, None

    lines = content.splitlines()
    for line_num, line in enumerate(lines, 1):
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue

        upper = clean.upper()

        if upper.startswith("FROM "):
            has_from = True

        if upper.startswith("CMD ") or upper.startswith("ENTRYPOINT "):
            has_cmd_or_entrypoint = True
            cmd_or_entrypoint = clean.split(maxsplit=1)[1].strip()

        if upper.startswith("EXPOSE "):
            parts = clean.split()
            if len(parts) > 1:
                port_match = re.search(r"(\d+)", parts[1])
                if port_match:
                    try:
                        exposed_port = int(port_match.group(1))
                    except ValueError:
                        pass

        # Security check: copying credentials or env files
        if re.search(r"COPY\s+.*(\.env|id_rsa|\.git|\.pem|credentials)", clean, re.IGNORECASE):
            issues.append(f"Line {line_num}: Sensitive file patterns copied into image: '{clean}'")

    if not has_from:
        issues.append("Missing required FROM instruction")
    if not has_cmd_or_entrypoint:
        issues.append("Missing CMD or ENTRYPOINT instruction")

    is_valid = has_from and has_cmd_or_entrypoint and len(issues) == 0
    return is_valid, issues, exposed_port, cmd_or_entrypoint


# ============================================================
# SUBPROJECT & MONOREPO DISCOVERY
# ============================================================

IGNORED_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "target", "build", "dist",
    "venv", ".venv", "env", "__pycache__", ".idea", ".vscode", ".terraform"
}


def discover_subprojects(root_path: Path, max_depth: int = 2) -> List[Dict[str, Any]]:
    """Scan directory hierarchy for subprojects in a monorepo."""
    subprojects: List[Dict[str, Any]] = []

    def _scan(current_path: Path, current_depth: int):
        if current_depth > max_depth:
            return

        try:
            entries = list(current_path.iterdir())
        except (PermissionError, OSError):
            return

        for entry in entries:
            if not entry.is_dir() or entry.name in IGNORED_DIRS or entry.name.startswith("."):
                continue

            rel_path = str(entry.relative_to(root_path)).replace("\\", "/")
            detected = _detect_single_root(entry, rel_root=rel_path)
            if detected.language != "unknown" and detected.confidence >= 0.5:
                subprojects.append(detected.to_dict())
            else:
                _scan(entry, current_depth + 1)

    _scan(root_path, 1)
    return subprojects


# ============================================================
# PYTHON DETECTOR
# ============================================================

def _detect_python(project_path: Path, files: Set[str], rel_root: str = ".") -> Optional[DetectionResult]:
    """Analyze Python projects with precise manifest and dependency detection."""
    has_req = "requirements.txt" in files
    has_pyproject = "pyproject.toml" in files
    has_pipfile = "pipfile" in files or "Pipfile" in files
    has_setup = "setup.py" in files or "setup.cfg" in files

    # Find python source files directly at root or one level deep
    py_files = [f for f in files if f.endswith(".py")]

    # If no files at root, check if any .py files exist in immediate folders
    if not py_files:
        try:
            py_files = [str(p.relative_to(project_path)).replace("\\", "/")
                        for p in project_path.glob("*.py")]
            if not py_files:
                py_files = [str(p.relative_to(project_path)).replace("\\", "/")
                            for p in project_path.glob("*/*.py") if not any(ign in p.parts for ign in IGNORED_DIRS)]
        except (PermissionError, OSError):
            py_files = []

    if not (has_req or has_pyproject or has_pipfile or has_setup or len(py_files) >= 1):
        return None

    confidence = 0.5
    if has_req or has_pyproject:
        confidence = 0.95
    elif has_pipfile or has_setup:
        confidence = 0.85
    elif py_files:
        confidence = 0.65

    # Determine dependency manager and install command
    dep_manager = "none"
    install_cmd = ""

    if has_req:
        dep_manager = "pip"
        install_cmd = "pip install --no-cache-dir -r requirements.txt"
    elif has_pyproject:
        pyproject_path = project_path / "pyproject.toml"
        dep_manager = "pyproject"
        install_cmd = "pip install --no-cache-dir ."
        if pyproject_path.exists():
            try:
                content = pyproject_path.read_text(encoding="utf-8", errors="ignore")
                toml_data = tomllib.loads(content)
                if "tool" in toml_data and "poetry" in toml_data["tool"]:
                    dep_manager = "poetry"
                    install_cmd = "poetry install --no-root"
            except Exception:
                pass
    elif has_pipfile:
        dep_manager = "pipenv"
        install_cmd = "pipenv install --system --deploy"
    elif has_setup:
        dep_manager = "setup"
        install_cmd = "pip install --no-cache-dir ."
    else:
        dep_manager = "none"
        install_cmd = ""

    # Determine framework
    framework: Optional[str] = None
    framework_indicators = {
        "fastapi": ["fastapi", "uvicorn"],
        "flask": ["flask", "werkzeug"],
        "django": ["django"],
        "tornado": ["tornado"],
    }

    req_text = ""
    for req_file in ["requirements.txt", "pyproject.toml", "Pipfile", "pipfile"]:
        rf_path = project_path / req_file
        if rf_path.exists():
            try:
                req_text += rf_path.read_text(encoding="utf-8", errors="ignore").lower() + "\n"
            except Exception:
                pass

    for fw, indicators in framework_indicators.items():
        if any(ind in req_text for ind in indicators):
            framework = fw
            break

    # If framework not found in manifests, inspect Python source files
    if not framework:
        for py_name in py_files[:10]:
            pfile = project_path / py_name
            if pfile.exists() and pfile.is_file():
                try:
                    src = pfile.read_text(encoding="utf-8", errors="ignore").lower()
                    if "from fastapi" in src or "import fastapi" in src:
                        framework = "fastapi"
                        break
                    elif "from flask" in src or "import flask" in src:
                        framework = "flask"
                        break
                    elif "django" in src:
                        framework = "django"
                        break
                except Exception:
                    pass

    # Determine start command and port
    port = 5000
    start_cmd = "python app.py"
    health_check_path = "/"

    if framework == "fastapi":
        port = 8000
        health_check_path = "/health"
        if "main.py" in files or any(f.endswith("main.py") for f in py_files):
            start_cmd = "uvicorn main:app --host 0.0.0.0 --port 8000"
        elif "app.py" in files or any(f.endswith("app.py") for f in py_files):
            start_cmd = "uvicorn app:app --host 0.0.0.0 --port 8000"
        else:
            start_cmd = "uvicorn main:app --host 0.0.0.0 --port 8000"
    elif framework == "flask":
        port = 5000
        health_check_path = "/"
        if "app.py" in files:
            start_cmd = "python app.py"
        elif "wsgi.py" in files:
            start_cmd = "python wsgi.py"
        elif "main.py" in files:
            start_cmd = "python main.py"
        else:
            start_cmd = f"python {py_files[0]}" if py_files else "python app.py"
    elif framework == "django":
        port = 8000
        start_cmd = "python manage.py runserver 0.0.0.0:8000"
        health_check_path = "/"
    else:
        # Generic python
        if "app.py" in files:
            start_cmd = "python app.py"
        elif "main.py" in files:
            start_cmd = "python main.py"
        elif "server.py" in files:
            start_cmd = "python server.py"
        elif py_files:
            start_cmd = f"python {py_files[0]}"

    # Only schedule a test runner when the repository contains Python tests.
    # unittest exits with code 5 when it discovers zero tests, which Jenkins
    # correctly treats as a failure; avoid generating a test stage for apps
    # that do not include tests yet.
    test_files = (
        path
        for pattern in ("test*.py", "*_test.py")
        for path in project_path.rglob(pattern)
        if not any(
            part in IGNORED_DIRS or part.startswith(".")
            for part in path.relative_to(project_path).parts[:-1]
        )
    )
    has_test_files = next(test_files, None) is not None
    test_cmd: Optional[str] = None
    if has_test_files:
        if "pytest.ini" in files or "pytest" in req_text:
            test_cmd = "pytest"
        else:
            test_cmd = "python -m unittest discover"

    # Language version
    lang_version = "3.12"
    runtime_txt = project_path / "runtime.txt"
    if runtime_txt.exists():
        try:
            m = re.search(r"python-(\d+\.\d+)", runtime_txt.read_text().strip())
            if m:
                lang_version = m.group(1)
        except Exception:
            pass

    return DetectionResult(
        language="python",
        language_version=lang_version,
        framework=framework,
        application_type="web-api" if framework in ("fastapi", "flask", "django") else "cli",
        project_root=rel_root,
        dependency_manager=dep_manager,
        has_requirements_file=has_req,
        has_pyproject_file=has_pyproject,
        install_command=install_cmd,
        build_command=None,
        test_command=test_cmd,
        start_command=start_cmd,
        port=port,
        health_check_path=health_check_path,
        dockerfile_template="python",
        confidence=confidence,
    )


# ============================================================
# NODE.JS DETECTOR
# ============================================================

def _detect_node(project_path: Path, files: Set[str], rel_root: str = ".") -> Optional[DetectionResult]:
    """Analyze Node.js / TypeScript projects."""
    if "package.json" not in files:
        return None

    confidence = 0.95
    pkg_json_path = project_path / "package.json"
    pkg_data: Dict[str, Any] = {}

    try:
        content = pkg_json_path.read_text(encoding="utf-8", errors="ignore")
        pkg_data = json.loads(content)
    except Exception as exc:
        logger.warning("Could not parse package.json: %s", exc)

    scripts = pkg_data.get("scripts", {})
    deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}

    # Detect package manager
    dep_manager = "npm"
    install_cmd = "npm install"
    if "yarn.lock" in files:
        dep_manager = "yarn"
        install_cmd = "yarn install --frozen-lockfile"
    elif "pnpm-lock.yaml" in files:
        dep_manager = "pnpm"
        install_cmd = "pnpm install --frozen-lockfile"
    elif "package-lock.json" in files:
        dep_manager = "npm"
        install_cmd = "npm ci"

    # Framework detection
    framework: Optional[str] = None
    if "next" in deps:
        framework = "nextjs"
    elif "@nestjs/core" in deps:
        framework = "nestjs"
    elif "express" in deps:
        framework = "express"
    elif "fastify" in deps:
        framework = "fastify"
    elif "react" in deps:
        framework = "react"
    elif "vue" in deps:
        framework = "vue"

    # Build command
    build_cmd: Optional[str] = None
    if "build" in scripts:
        build_cmd = f"{dep_manager} run build"

    # Test command
    test_cmd: Optional[str] = None
    if "test" in scripts:
        raw_test = scripts["test"]
        if "no test specified" not in raw_test.lower():
            test_cmd = f"{dep_manager} test"

    port = 3000
    start_cmd = "npm start"
    health_check_path = "/"

    if "start" in scripts:
        start_cmd = f"{dep_manager} start"
    elif "main" in pkg_data:
        start_cmd = f"node {pkg_data['main']}"
    elif "server.js" in files:
        start_cmd = "node server.js"
    elif "index.js" in files:
        start_cmd = "node index.js"
    elif "app.js" in files:
        start_cmd = "node app.js"

    if framework == "nestjs":
        health_check_path = "/health"

    node_version = "20"
    engines = pkg_data.get("engines", {})
    if "node" in engines:
        m = re.search(r"(\d+)", engines["node"])
        if m:
            node_version = m.group(1)

    return DetectionResult(
        language="node",
        language_version=node_version,
        framework=framework,
        application_type="web-app" if framework in ("nextjs", "react", "vue") else "web-api",
        project_root=rel_root,
        dependency_manager=dep_manager,
        install_command=install_cmd,
        build_command=build_cmd,
        test_command=test_cmd,
        start_command=start_cmd,
        port=port,
        health_check_path=health_check_path,
        dockerfile_template="node",
        confidence=confidence,
    )


# ============================================================
# JAVA DETECTOR
# ============================================================

def _detect_java(project_path: Path, files: Set[str], rel_root: str = ".") -> Optional[DetectionResult]:
    """Analyze Java projects (Maven and Gradle)."""
    is_maven = "pom.xml" in files
    is_gradle = "build.gradle" in files or "build.gradle.kts" in files

    if not (is_maven or is_gradle):
        return None

    confidence = 0.95
    lang_version = "21"
    framework = "spring-boot"
    port = 8080
    health_check_path = "/actuator/health"

    if is_maven:
        dep_manager = "maven"
        pom_path = project_path / "pom.xml"
        has_mvnw = "mvnw" in files or "mvnw.cmd" in files
        mvn_bin = "./mvnw" if has_mvnw else "mvn"

        install_cmd = f"{mvn_bin} dependency:go-offline"
        build_cmd = f"{mvn_bin} clean package -DskipTests"
        test_cmd = f"{mvn_bin} test"
        start_cmd = "java -jar target/*.jar"

        if pom_path.exists():
            try:
                pom_text = pom_path.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"<java\.version>(\d+)</java\.version>", pom_text)
                if m:
                    lang_version = m.group(1)
                elif "<maven.compiler.source>17</maven.compiler.source>" in pom_text:
                    lang_version = "17"

                if "spring-boot" in pom_text:
                    framework = "spring-boot"
                elif "quarkus" in pom_text:
                    framework = "quarkus"
                    start_cmd = "java -jar target/quarkus-app/quarkus-run.jar"
                elif "micronaut" in pom_text:
                    framework = "micronaut"
            except Exception:
                pass

        return DetectionResult(
            language="java-maven",
            language_version=lang_version,
            framework=framework,
            application_type="web-api",
            project_root=rel_root,
            dependency_manager=dep_manager,
            install_command=install_cmd,
            build_command=build_cmd,
            test_command=test_cmd,
            start_command=start_cmd,
            port=port,
            health_check_path=health_check_path,
            dockerfile_template="java-maven",
            confidence=confidence,
        )
    else:
        dep_manager = "gradle"
        has_gradlew = "gradlew" in files or "gradlew.bat" in files
        gradle_bin = "./gradlew" if has_gradlew else "gradle"

        install_cmd = f"{gradle_bin} dependencies"
        build_cmd = f"{gradle_bin} build -x test"
        test_cmd = f"{gradle_bin} test"
        start_cmd = "java -jar build/libs/*.jar"

        return DetectionResult(
            language="java-gradle",
            language_version=lang_version,
            framework=framework,
            application_type="web-api",
            project_root=rel_root,
            dependency_manager=dep_manager,
            install_command=install_cmd,
            build_command=build_cmd,
            test_command=test_cmd,
            start_command=start_cmd,
            port=port,
            health_check_path=health_check_path,
            dockerfile_template="java-gradle",
            confidence=confidence,
        )


# ============================================================
# GO DETECTOR
# ============================================================

def _detect_go(project_path: Path, files: Set[str], rel_root: str = ".") -> Optional[DetectionResult]:
    """Analyze Go projects."""
    has_go_mod = "go.mod" in files
    has_go_files = any(f.endswith(".go") for f in files)

    if not (has_go_mod or has_go_files):
        return None

    confidence = 0.9 if has_go_mod else 0.6
    go_version = "1.22"

    if has_go_mod:
        try:
            content = (project_path / "go.mod").read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^go\s+(\d+\.\d+)", content, re.MULTILINE)
            if m:
                go_version = m.group(1)
        except Exception:
            pass

    return DetectionResult(
        language="go",
        language_version=go_version,
        framework=None,
        application_type="web-api",
        project_root=rel_root,
        dependency_manager="go",
        install_command="go mod download" if has_go_mod else "",
        build_command="go build -o /app/server .",
        test_command="go test ./...",
        start_command="./server",
        port=8080,
        health_check_path="/health",
        dockerfile_template="go",
        confidence=confidence,
    )


# ============================================================
# SINGLE ROOT DETECTION
# ============================================================

def _detect_single_root(project_path: Path, rel_root: str = ".") -> DetectionResult:
    """Analyze a single directory root."""
    try:
        files = {file.name for file in project_path.iterdir() if file.is_file()}
    except (PermissionError, OSError):
        files = set()

    # Check for existing Dockerfile
    dockerfile_path = project_path / "Dockerfile"
    has_dockerfile = "Dockerfile" in files
    is_valid_dockerfile = False
    dockerfile_issues: List[str] = []
    exposed_port: Optional[int] = None
    custom_cmd: Optional[str] = None

    if has_dockerfile:
        is_valid_dockerfile, dockerfile_issues, exposed_port, custom_cmd = inspect_existing_dockerfile(dockerfile_path)

    # Try detectors in order
    result: Optional[DetectionResult] = None

    # 1. Python
    res = _detect_python(project_path, files, rel_root=rel_root)
    if res and (result is None or res.confidence > result.confidence):
        result = res

    # 2. Node.js
    res = _detect_node(project_path, files, rel_root=rel_root)
    if res and (result is None or res.confidence > result.confidence):
        result = res

    # 3. Java
    res = _detect_java(project_path, files, rel_root=rel_root)
    if res and (result is None or res.confidence > result.confidence):
        result = res

    # 4. Go
    res = _detect_go(project_path, files, rel_root=rel_root)
    if res and (result is None or res.confidence > result.confidence):
        result = res

    if not result:
        result = DetectionResult(
            language="unknown",
            language_version="",
            application_type="unknown",
            project_root=rel_root,
            dockerfile_template="unknown",
            confidence=0.0,
            warnings=["No known technology stack indicators found."],
        )

    result.has_existing_dockerfile = has_dockerfile
    result.existing_dockerfile_valid = is_valid_dockerfile
    result.existing_dockerfile_issues = dockerfile_issues

    if exposed_port is not None:
        result.port = exposed_port
    if custom_cmd is not None and is_valid_dockerfile:
        result.start_command = custom_cmd

    return result


# ============================================================
# PRIMARY ENTRY POINT
# ============================================================

def detect_project(project_path: Path | str, subpath: Optional[str] = None) -> DetectionResult:
    """Analyze a project directory, auto-detecting technology stack and build configuration.

    Supports single-app repositories and monorepositories.

    Args:
        project_path: Absolute or relative path to the repository root.
        subpath: Optional subdirectory path within the repository to inspect.

    Returns:
        DetectionResult: Structured detection findings.
    """
    root = Path(project_path).resolve()
    target = (root / subpath).resolve() if subpath else root

    if not target.exists() or not target.is_dir():
        return DetectionResult(
            language="unknown",
            language_version="",
            project_root=str(subpath or "."),
            dockerfile_template="unknown",
            confidence=0.0,
            warnings=[f"Path does not exist or is not a directory: {target}"],
        )

    rel_root = str(target.relative_to(root)).replace("\\", "/") if target != root else "."
    result = _detect_single_root(target, rel_root=rel_root)

    # If root detection is unknown or low confidence, check for subprojects (monorepo)
    if target == root and (result.language == "unknown" or result.confidence < 0.7):
        subprojects = discover_subprojects(root)
        if subprojects:
            result.subprojects = subprojects
            if len(subprojects) == 1:
                primary = subprojects[0]
                result = DetectionResult(**primary)
                result.subprojects = subprojects
                result.warnings.append(
                    f"Monorepo detected: auto-selected root application in '{result.project_root}'."
                )
            else:
                result.application_type = "monorepo"
                result.warnings.append(
                    f"Monorepo detected with {len(subprojects)} subprojects. "
                    f"Please specify application subpath from: {[s['project_root'] for s in subprojects]}"
                )

    return result
