import json
import uuid
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from backend.config import settings

DEPLOYMENTS_FILE = settings.workspace_root / ".deployments.json"

class DeploymentManager:
    def __init__(self):
        self._load_deployments()

    def _load_deployments(self):
        self.deployments: List[Dict[str, Any]] = []
        if DEPLOYMENTS_FILE.exists():
            try:
                data = json.loads(DEPLOYMENTS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.deployments = data
            except Exception:
                self.deployments = []

    def _save_deployments(self):
        try:
            DEPLOYMENTS_FILE.write_text(json.dumps(self.deployments, indent=2), encoding="utf-8")
        except Exception:
            pass

    def list_deployments(self) -> List[Dict[str, Any]]:
        # Refresh status on read
        return self.deployments

    def get_deployment(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        for d in self.deployments:
            if d["id"] == deployment_id:
                return d
        return None

    def record_deployment(
        self,
        project_id: str,
        project_name: str,
        image_name: str,
        container_name: str,
        port: int,
        git_commit: Optional[str] = None,
        validation_status: str = "passed",
        status: str = "healthy",
        logs: str = "",
    ) -> Dict[str, Any]:
        dep_id = f"dep-{str(uuid.uuid4())[:8]}"
        record = {
            "id": dep_id,
            "project_id": project_id,
            "project_name": project_name,
            "git_commit": git_commit or "untracked",
            "validation_status": validation_status,
            "image_name": image_name,
            "container_name": container_name,
            "port": port,
            "url": f"http://localhost:{port}",
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "logs": logs,
        }
        self.deployments.insert(0, record)
        self._save_deployments()
        return record

    def check_health(self, url: str, timeout: int = 4) -> Dict[str, Any]:
        """Verify if deployed endpoint responds to HTTP requests."""
        try:
            resp = requests.get(url, timeout=timeout)
            is_healthy = resp.status_code < 500
            return {
                "healthy": is_healthy,
                "status_code": resp.status_code,
                "message": f"Service responded with HTTP {resp.status_code}",
            }
        except requests.exceptions.ConnectionError:
            return {
                "healthy": False,
                "status_code": 0,
                "message": "Connection refused - container application not responding on designated port",
            }
        except requests.exceptions.Timeout:
            return {
                "healthy": False,
                "status_code": 0,
                "message": f"Connection timed out after {timeout} seconds",
            }
        except Exception as e:
            return {
                "healthy": False,
                "status_code": 0,
                "message": str(e),
            }

    def update_status(self, deployment_id: str, status: str, log_append: str = ""):
        dep = self.get_deployment(deployment_id)
        if dep:
            dep["status"] = status
            if log_append:
                dep["logs"] = (dep.get("logs", "") + "\n" + log_append).strip()
            self._save_deployments()
