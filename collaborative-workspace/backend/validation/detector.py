from pathlib import Path
from typing import Dict, Any, List

def detect_project(project_path: Path) -> Dict[str, Any]:
    """
    Detect project type, entrypoint, configuration, and dependencies.
    Unifies Automator and Collaborative Workspace detector algorithms.
    """
    project_path = Path(project_path)
    if not project_path.exists():
        return {
            "type": "unknown",
            "framework": None,
            "entrypoint": None,
            "detected_files": [],
        }

    files = [f for f in project_path.rglob("*") if f.is_file()]
    file_names = {f.name for f in files}

    detected_type = "unknown"
    framework = None
    entrypoint = None

    # Python Detection
    if "requirements.txt" in file_names or "pyproject.toml" in file_names or any(f.suffix == ".py" for f in files):
        detected_type = "python"
        if "app.py" in file_names:
            entrypoint = "app.py"
        elif "main.py" in file_names:
            entrypoint = "main.py"
        elif any(f.suffix == ".py" for f in files):
            py_files = [f.name for f in files if f.suffix == ".py"]
            entrypoint = py_files[0] if py_files else None

        # Framework detection
        if "requirements.txt" in file_names:
            try:
                content = (project_path / "requirements.txt").read_text(errors="ignore").lower()
                if "fastapi" in content:
                    framework = "FastAPI"
                elif "flask" in content:
                    framework = "Flask"
                elif "django" in content:
                    framework = "Django"
            except Exception:
                pass

    # Node.js Detection
    elif "package.json" in file_names:
        detected_type = "node"
        entrypoint = "index.js" if "index.js" in file_names else "package.json"
        try:
            content = (project_path / "package.json").read_text(errors="ignore").lower()
            if "express" in content:
                framework = "Express"
            elif "vue" in content:
                framework = "Vue.js"
            elif "react" in content:
                framework = "React"
        except Exception:
            pass

    # Java Detection (Maven or Gradle)
    elif "pom.xml" in file_names or "build.gradle" in file_names or "build.gradle.kts" in file_names:
        detected_type = "java"
        if "pom.xml" in file_names:
            entrypoint = "pom.xml"
            framework = "Maven"
        else:
            entrypoint = "build.gradle"
            framework = "Gradle"

    return {
        "type": detected_type,
        "framework": framework,
        "entrypoint": entrypoint,
        "files_count": len(files),
        "detected_files": [f.name for f in files[:20]],
    }
