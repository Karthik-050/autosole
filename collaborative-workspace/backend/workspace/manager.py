from pathlib import Path, PurePosixPath
import os
import uuid
import shutil
import stat
import json
from zipfile import ZipFile
from typing import Dict, Any, List, Optional
from datetime import datetime

from sandbox.runner import SandboxRunner
from backend.config import settings
from backend.git.manager import GitManager
from backend.validation.detector import detect_project

BASE_DIR = settings.workspace_root


class WorkspaceManager:

    def __init__(self):
        self.sandbox = SandboxRunner()
        self.base_dir = BASE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._meta_file = self.base_dir / ".workspaces_meta.json"
        self._load_meta()

    def _load_meta(self):
        self._meta = {}
        if self._meta_file.exists():
            try:
                self._meta = json.loads(self._meta_file.read_text(encoding="utf-8"))
            except Exception:
                self._meta = {}

    def _save_meta(self):
        try:
            self._meta_file.write_text(json.dumps(self._meta, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _safe_path(self, wid: str, filename: Optional[str] = None) -> Path:
        """Prevent path traversal vulnerabilities."""
        ws_path = (self.base_dir / wid).resolve()
        if not ws_path.is_relative_to(self.base_dir.resolve()):
            raise PermissionError("Path traversal outside workspace directory forbidden")

        if filename:
            file_path = (ws_path / filename).resolve()
            if not file_path.is_relative_to(ws_path):
                raise PermissionError("File path traversal outside workspace forbidden")
            return file_path
        return ws_path

    def create_workspace(self, name: Optional[str] = None, template: Optional[str] = None):
        wid = str(uuid.uuid4())
        path = self._safe_path(wid)
        path.mkdir(parents=True, exist_ok=True)

        meta_info = {
            "name": name or f"Project-{wid[:8]}",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "template": template or "empty",
        }
        self._meta[wid] = meta_info
        self._save_meta()

        if template == "python":
            (path / "app.py").write_text(
                'from flask import Flask\n\napp = Flask(__name__)\n\n@app.route("/")\ndef home():\n    return "Hello from Collaborative Workspace!"\n\nif __name__ == "__main__":\n    app.run(host="0.0.0.0", port=5000)\n',
                encoding="utf-8"
            )
            (path / "requirements.txt").write_text("flask\n", encoding="utf-8")
        elif template == "fastapi":
            (path / "main.py").write_text(
                'from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get("/")\ndef home():\n    return {"message": "Hello from FastAPI workspace"}\n',
                encoding="utf-8"
            )
            (path / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")

        # Initialize each managed workspace as its own repository so the Git
        # view is ready as soon as the project is created.
        GitManager(path).init_repo()
        return wid

    def list_workspaces(self):
        if not self.base_dir.exists():
            return []
        dirs = [w.name for w in self.base_dir.iterdir() if w.is_dir() and not w.name.startswith(".")]
        return dirs

    def list_workspaces_detailed(self) -> List[Dict[str, Any]]:
        dirs = self.list_workspaces()
        results = []
        for wid in dirs:
            details = self.get_workspace_details(wid)
            results.append(details)
        return results

    def get_workspace_details(self, wid: str) -> Dict[str, Any]:
        ws_path = self._safe_path(wid)
        if not ws_path.exists():
            raise FileNotFoundError("Workspace not found")

        meta = self._meta.get(wid, {})
        detection = detect_project(ws_path)
        files = self.list_files(wid)

        return {
            "id": wid,
            "name": meta.get("name", f"Project-{wid[:8]}"),
            "path": str(ws_path),
            "project_type": detection["type"],
            "framework": detection["framework"],
            "entrypoint": detection["entrypoint"],
            "files_count": len(files),
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at"),
        }

    def delete_workspace(self, wid):
        path = self._safe_path(wid)
        if not path.exists():
            raise Exception("Workspace not found")

        def remove_readonly(func, target_path, exc_info):
            try:
                os.chmod(target_path, stat.S_IWRITE)
                func(target_path)
            except OSError:
                raise

        shutil.rmtree(path, onerror=remove_readonly)
        if wid in self._meta:
            del self._meta[wid]
            self._save_meta()

    def create_file(self, wid, filename):
        path = self._safe_path(wid, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        if wid in self._meta:
            self._meta[wid]["updated_at"] = datetime.now().isoformat()
            self._save_meta()
        return str(path)

    def write_file(self, wid, filename, content):
        path = self._safe_path(wid, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if wid in self._meta:
            self._meta[wid]["updated_at"] = datetime.now().isoformat()
            self._save_meta()

    def read_file(self, wid, filename):
        path = self._safe_path(wid, filename)
        if not path.exists():
            raise FileNotFoundError(f"File '{filename}' does not exist")
        return path.read_text(encoding="utf-8", errors="replace")

    def delete_file(self, wid, filename):
        path = self._safe_path(wid, filename)
        if path.exists():
            path.unlink()
            if wid in self._meta:
                self._meta[wid]["updated_at"] = datetime.now().isoformat()
                self._save_meta()

    def list_files(self, wid):
        path = self._safe_path(wid)
        if not path.exists():
            raise Exception("Workspace not found")

        file_list = []
        for f in path.rglob("*"):
            if f.is_file() and not any(p.startswith(".") for p in f.parts):
                file_list.append(str(f.relative_to(path)).replace("\\", "/"))
        return file_list

    def run_file(self, wid, filename):
        return self.sandbox.run(wid, filename)

    def import_from_zip(self, zip_path: Path, project_name: Optional[str] = None) -> str:
        """
        Reuses Automator's zip extraction logic into a managed workspace.
        """
        zip_path = Path(zip_path)
        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")

        wid = str(uuid.uuid4())
        project_path = self._safe_path(wid)
        project_path.mkdir(parents=True, exist_ok=True)

        temp_path = self.base_dir / f".temp_{wid}"
        temp_path.mkdir(parents=True, exist_ok=True)

        try:
            with ZipFile(zip_path, "r") as zf:
                # Validate members before extracting. ZipInfo.filename always uses
                # forward slashes; reject absolute paths, traversal, and symlinks.
                for member in zf.infolist():
                    normalized_name = member.filename.replace("\\", "/")
                    member_path = PurePosixPath(normalized_name)
                    mode = member.external_attr >> 16
                    if (
                        member_path.is_absolute()
                        or ".." in member_path.parts
                        or (member_path.parts and ":" in member_path.parts[0])
                        or (mode & 0o170000) == 0o120000
                    ):
                        raise ValueError(f"Unsafe path in ZIP archive: {member.filename!r}")

                    destination = (temp_path / Path(*member_path.parts)).resolve()
                    if not destination.is_relative_to(temp_path.resolve()):
                        raise ValueError(f"Unsafe path in ZIP archive: {member.filename!r}")

                zf.extractall(temp_path)

            items = list(temp_path.iterdir())
            if len(items) == 1 and items[0].is_dir():
                root_folder = items[0]
                for item in root_folder.iterdir():
                    shutil.move(str(item), str(project_path / item.name))
            else:
                for item in items:
                    shutil.move(str(item), str(project_path / item.name))

            GitManager(project_path).init_repo()

            meta_name = project_name or zip_path.stem
            self._meta[wid] = {
                "name": meta_name,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "template": "zip_import",
            }
            self._save_meta()
            return wid
        except Exception:
            self._meta.pop(wid, None)
            shutil.rmtree(project_path, ignore_errors=True)
            self._save_meta()
            raise
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path, ignore_errors=True)
