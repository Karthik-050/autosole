import hashlib
import hmac
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException, Request

from backend.config import settings
from backend.git.manager import GitManager
from backend.routers.dashboard import jenkins_manager, ws_manager
from backend.validation.detector import detect_project

router = APIRouter(prefix="/webhooks", tags=["Git Webhooks"])


def verify_github_signature(body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, f"sha256={digest}")


def normalize_github_remote(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    parsed = urlsplit(url.strip())
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or len(parts) != 2:
        return None
    repository = parts[1].removesuffix(".git")
    return f"https://github.com/{parts[0]}/{repository}".lower()


def _container_port(project_type: str) -> int:
    return 3000 if project_type == "node" else 5000


@router.post("/github")
async def github_push_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
) -> Dict[str, Any]:
    if not settings.github_webhook_secret:
        raise HTTPException(status_code=503, detail="GITHUB_WEBHOOK_SECRET is not configured")

    body = await request.body()
    if not verify_github_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")
    if x_github_event != "push":
        return {"accepted": True, "ignored": True, "reason": "Only push events trigger CI/CD"}

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON payload") from exc

    repository = payload.get("repository") or {}
    incoming_remote = normalize_github_remote(repository.get("clone_url") or repository.get("html_url"))
    ref = payload.get("ref", "")
    if not incoming_remote or not ref.startswith("refs/heads/"):
        raise HTTPException(status_code=400, detail="Push payload is missing a valid GitHub repository or branch")
    branch = ref.removeprefix("refs/heads/")

    triggered = []
    for project_id in ws_manager.list_workspaces():
        project_path = ws_manager._safe_path(project_id)
        git = GitManager(project_path)
        if normalize_github_remote(git.get_remote_url()) != incoming_remote:
            continue
        if git.get_current_branch() != branch:
            continue

        project = detect_project(project_path)
        try:
            job = jenkins_manager.create_or_update_repository_job(
                project_id=project_id,
                repository_url=git.get_remote_url(),
                branch=branch,
                project_type=project["type"],
                entrypoint=project.get("entrypoint"),
                container_port=_container_port(project["type"]),
            )
            build = jenkins_manager.trigger_build(job["job_name"])
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not queue Jenkins build: {exc}") from exc

        triggered.append({
            "project_id": project_id,
            "job_name": job["job_name"],
            "queue_id": build.get("queue_id"),
            "head_commit": (payload.get("head_commit") or {}).get("id"),
        })

    return {"accepted": True, "triggered": triggered, "ignored": not triggered}
