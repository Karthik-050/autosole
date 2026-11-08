from pathlib import Path
import os
from typing import Dict, Any
from dotenv import load_dotenv

# Root paths
BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR.parent / ".env", override=False)
load_dotenv(BACKEND_DIR.parent.parent / ".env", override=False)
WORKSPACE_ROOT = (BACKEND_DIR.parent / "workspace").resolve()

# Automator root resolution (prefers new-automator, then automator, then external D:/automator)
_candidates = [
    (BACKEND_DIR.parent.parent / "new-automator").resolve(),
    (BACKEND_DIR.parent.parent / "automator").resolve(),
    Path("D:/automator").resolve(),
]
AUTOMATOR_ROOT = next((p for p in _candidates if p.exists()), _candidates[0])

# Ensure workspaces root exists
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

class Settings:
    def __init__(self):
        self.workspace_root: Path = WORKSPACE_ROOT
        self.automator_root: Path = AUTOMATOR_ROOT

        # Jenkins Configuration
        self.jenkins_url: str = os.getenv("JENKINS_URL", "http://localhost:8080")
        self.jenkins_username: str = os.getenv("JENKINS_USERNAME", "admin")
        self.jenkins_api_token: str = os.getenv("JENKINS_API_TOKEN", "")
        self.github_webhook_secret: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
        self.public_base_url: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
        self.github_jenkins_credential_id: str = os.getenv("GITHUB_JENKINS_CREDENTIAL_ID", "")

        # Docker Configuration
        self.docker_host: str = os.getenv("DOCKER_HOST", "")
        self.sandbox_image: str = os.getenv("SANDBOX_IMAGE", "python:3.10-slim")
        self.default_deploy_port: int = int(os.getenv("DEPLOY_PORT", "5001"))

        # Validation Policy
        self.enforce_mandatory_validation: bool = os.getenv("ENFORCE_VALIDATION", "true").lower() in ("true", "1", "yes")
        self.allow_warnings: bool = True

        # Pipeline Configuration
        self.default_job_name: str = "automator-deploy"
        self.execution_timeout_seconds: int = int(os.getenv("EXECUTION_TIMEOUT", "60"))

    def get_masked_config(self) -> Dict[str, Any]:
        """Return safe configuration without exposing plaintext secrets."""
        return {
            "workspace_root": str(self.workspace_root),
            "jenkins_url": self.jenkins_url,
            "jenkins_username": self.jenkins_username,
            "jenkins_token_configured": bool(self.jenkins_api_token),
            "github_webhook_secret_configured": bool(self.github_webhook_secret),
            "public_base_url_configured": bool(self.public_base_url),
            "docker_host": self.docker_host if self.docker_host else "local socket / pipe",
            "sandbox_image": self.sandbox_image,
            "default_deploy_port": self.default_deploy_port,
            "enforce_mandatory_validation": self.enforce_mandatory_validation,
            "execution_timeout_seconds": self.execution_timeout_seconds,
        }

    def update_config(self, updates: Dict[str, Any]):
        if "jenkins_url" in updates and updates["jenkins_url"] is not None:
            self.jenkins_url = str(updates["jenkins_url"]).strip()
        if "jenkins_username" in updates and updates["jenkins_username"] is not None:
            self.jenkins_username = str(updates["jenkins_username"]).strip()
        if "jenkins_api_token" in updates and updates["jenkins_api_token"]:
            self.jenkins_api_token = str(updates["jenkins_api_token"]).strip()
        if "enforce_mandatory_validation" in updates and updates["enforce_mandatory_validation"] is not None:
            self.enforce_mandatory_validation = bool(updates["enforce_mandatory_validation"])
        if "default_deploy_port" in updates and updates["default_deploy_port"]:
            self.default_deploy_port = int(updates["default_deploy_port"])
        if "sandbox_image" in updates and updates["sandbox_image"]:
            self.sandbox_image = str(updates["sandbox_image"]).strip()

settings = Settings()
