"""Automator Project Manager and Archive Extraction Module.

Handles robust archive extraction, intelligent project root detection (handling
nested folders, extra top-level directories, and OS metadata), and absolute path resolution.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
import shutil
import tempfile
from typing import Optional, Set
from zipfile import ZipFile, is_zipfile

from config import get_settings

logger = logging.getLogger(__name__)

# Files that strongly identify a project root directory
PROJECT_INDICATORS: Set[str] = {
    # Manifest files
    "requirements.txt",
    "pyproject.toml",
    "pipfile",
    "setup.py",
    "setup.cfg",
    "package.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "go.mod",
    "cargo.toml",
    # Common entry points
    "app.py",
    "main.py",
    "server.py",
    "index.js",
    "server.js",
    "application.py",
    "wsgi.py",
    "manage.py",
}

# Directories and files to ignore when searching for project root
IGNORED_SYSTEM_NAMES: Set[str] = {
    "__macosx",
    ".ds_store",
    "thumbs.db",
    ".git",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
}


def is_ignored_item(item: Path) -> bool:
    """Check if file or directory is OS metadata or tooling cache."""
    name = item.name.lower()
    return name in IGNORED_SYSTEM_NAMES or name.startswith("._")


def find_project_root(extracted_dir: Path) -> Path:
    """Identify the actual project root directory within an extracted archive.

    Handles:
    - Archives containing files directly at root.
    - Archives containing a single top-level folder wrapping the project.
    - Archives containing multiple nested wrapper directories (e.g. repo/branch/src).
    - Archives contaminated with macOS __MACOSX or .DS_Store files.

    Args:
        extracted_dir: Temporary directory where archive was extracted.

    Returns:
        Path: The directory containing project files or manifests.
    """
    current = extracted_dir.resolve()

    # Step 1: Follow single-folder nesting while skipping system metadata
    while True:
        try:
            valid_items = [item for item in current.iterdir() if not is_ignored_item(item)]
        except (PermissionError, OSError):
            break

        # Check if the current level already contains clear project indicators
        current_files = {item.name.lower() for item in valid_items if item.is_file()}
        if current_files & PROJECT_INDICATORS:
            return current

        # If exactly one directory exists and no files, unwrap one level down
        dirs = [item for item in valid_items if item.is_dir()]
        files = [item for item in valid_items if item.is_file()]

        if len(dirs) == 1 and len(files) == 0:
            current = dirs[0]
            continue
        break

    # Step 2: If no indicator was found at current level, search up to 3 levels deep
    # for a directory that contains manifest or entrypoint files
    best_candidate: Optional[Path] = None
    best_score = 0

    for candidate in [current, *[p for p in current.glob("*") if p.is_dir() and not is_ignored_item(p)],
                               *[p for p in current.glob("*/*") if p.is_dir() and not is_ignored_item(p)]]:
        try:
            items = {item.name.lower() for item in candidate.iterdir() if not is_ignored_item(item) and item.is_file()}
        except (PermissionError, OSError):
            continue

        score = len(items & PROJECT_INDICATORS)
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate and best_score > 0:
        return best_candidate

    return current


def sanitize_project_name(name: str) -> str:
    """Convert filename or project name into a safe filesystem identifier."""
    clean = name.lower().strip()
    clean = re.sub(r"[^a-z0-9_-]+", "-", clean)
    clean = re.sub(r"-+", "-", clean).strip("-")
    return clean or "project"


def extract_project(
    zip_path: Path | str,
    target_dir: Optional[Path | str] = None,
) -> Path:
    """Extract a project archive and position all project files at the project root.

    Args:
        zip_path: Path to the .zip archive.
        target_dir: Optional destination directory. Defaults to settings.PROJECTS_DIR / safe_name.

    Returns:
        Path: Absolute path to the extracted project root.

    Raises:
        FileNotFoundError: If zip file does not exist.
        ValueError: If file is not a valid zip archive.
        RuntimeError: If extraction fails or yields an empty directory.
    """
    settings = get_settings()
    zip_file = Path(zip_path).resolve()

    if not zip_file.exists():
        raise FileNotFoundError(f"Project ZIP file not found: {zip_file}")

    if not zip_file.is_file():
        raise ValueError(f"The selected path is not a file: {zip_file}")

    if zip_file.suffix.lower() != ".zip" or not is_zipfile(zip_file):
        raise ValueError(f"Invalid ZIP archive: {zip_file}")

    project_name = sanitize_project_name(zip_file.stem)

    if target_dir is not None:
        project_path = Path(target_dir).resolve()
    else:
        project_path = (settings.PROJECTS_DIR / project_name).resolve()

    # Clean up previous extraction
    if project_path.exists():
        shutil.rmtree(project_path, ignore_errors=True)

    # Use a secure temporary directory for extraction
    temp_dir = Path(tempfile.mkdtemp(prefix=f"automator_{project_name}_"))

    try:
        logger.info("Extracting %s into staging directory %s", zip_file, temp_dir)
        with ZipFile(zip_file, "r") as zf:
            # Prevent zip-slip vulnerability
            for member in zf.namelist():
                member_path = (temp_dir / member).resolve()
                if not member_path.is_relative_to(temp_dir.resolve()):
                    raise ValueError(f"Zip slip security vulnerability detected in archive entry: {member}")
            zf.extractall(temp_dir)

        # Detect the true project root
        actual_root = find_project_root(temp_dir)
        logger.info("Identified project root at: %s", actual_root)

        project_path.mkdir(parents=True, exist_ok=True)

        # Move all items from actual_root into project_path
        for item in actual_root.iterdir():
            if is_ignored_item(item):
                continue
            dest = project_path / item.name
            if item.is_dir():
                shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
            else:
                shutil.copy2(str(item), str(dest))

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # Validate non-empty project
    items = list(project_path.iterdir())
    if not items:
        raise RuntimeError(f"Extracted project directory is empty: {project_path}")

    logger.info("Project extraction completed at %s (%d files/folders)", project_path, len(items))
    return project_path
