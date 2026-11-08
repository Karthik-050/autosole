from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, SecretStr
from typing import Optional
from urllib.parse import urlsplit

from backend.git.manager import GitManager
from backend.routers.dashboard import jenkins_manager, ws_manager
from backend.config import settings
from backend.validation.detector import detect_project

router = APIRouter(prefix="/git", tags=["Git"])

class CommitRequest(BaseModel):
    message: str
    author: Optional[str] = None

class GitHubConnectRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=500)
    branch: Optional[str] = Field(None, max_length=255)
    access_token: Optional[SecretStr] = None

class GitPushRequest(BaseModel):
    access_token: Optional[SecretStr] = None

def _pull_repository_and_start_pipeline(project_id: str, p_path, req: GitHubConnectRequest):
    git = GitManager(p_path)
    repository = git.connect_github_repository(
        req.url,
        req.branch,
        req.access_token.get_secret_value() if req.access_token else None,
    )
    try:
        project = detect_project(p_path)
        container_port = 5000 if project["type"] == "python" else 3000
        job = jenkins_manager.create_or_update_repository_job(
            project_id=project_id,
            repository_url=repository["remote"],
            branch=repository["branch"],
            project_type=project["type"],
            entrypoint=project.get("entrypoint"),
            container_port=container_port,
        )
        build = jenkins_manager.trigger_build(job["job_name"])
        webhook_url = f"{settings.public_base_url}/api/webhooks/github" if settings.public_base_url else None
        return {
            "repository": repository,
            "pipeline": {"job_name": job["job_name"], "queue_id": build.get("queue_id"), "status": "queued"},
            "webhook": {
                "callback_url": webhook_url,
                "endpoint": "/api/webhooks/github",
                "secret_configured": bool(settings.github_webhook_secret),
                "event": "push",
            },
        }
    except Exception as e:
        webhook_url = f"{settings.public_base_url}/api/webhooks/github" if settings.public_base_url else None
        return {
            "repository": repository,
            "pipeline": None,
            "pipeline_error": str(e),
            "webhook": {
                "callback_url": webhook_url,
                "endpoint": "/api/webhooks/github",
                "secret_configured": bool(settings.github_webhook_secret),
                "event": "push",
            },
        }

@router.get("/{project_id}/status")
def get_git_status(project_id: str):
    try:
        p_path = ws_manager._safe_path(project_id)
        git = GitManager(p_path)
        return {"status": git.get_status()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{project_id}/init")
def init_git_repo(project_id: str):
    try:
        p_path = ws_manager._safe_path(project_id)
        git = GitManager(p_path)
        return git.init_repo()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{project_id}/connect")
def connect_github_repository(project_id: str, req: GitHubConnectRequest):
    try:
        p_path = ws_manager._safe_path(project_id)
        return _pull_repository_and_start_pipeline(project_id, p_path, req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/connect")
def create_project_from_github_repository(req: GitHubConnectRequest):
    """Create a fresh project from GitHub, then start its CI/CD pipeline."""
    project_id = None
    try:
        repository_name = urlsplit(req.url.strip()).path.rstrip("/").split("/")[-1].removesuffix(".git")
        project_name = repository_name[:100] or "GitHub Repository"
        project_id = ws_manager.create_workspace(name=project_name, template="empty")
        p_path = ws_manager._safe_path(project_id)
        result = _pull_repository_and_start_pipeline(project_id, p_path, req)
        result["project_id"] = project_id
        return result
    except Exception as e:
        if project_id:
            try:
                ws_manager.delete_workspace(project_id)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{project_id}/commit")
def commit_changes(project_id: str, req: CommitRequest):
    try:
        p_path = ws_manager._safe_path(project_id)
        git = GitManager(p_path)
        return git.commit(message=req.message, author=req.author)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{project_id}/push")
def push_commits(project_id: str, req: GitPushRequest):
    try:
        p_path = ws_manager._safe_path(project_id)
        git = GitManager(p_path)
        token = req.access_token.get_secret_value() if req.access_token else None
        return git.push_to_remote(access_token=token)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{project_id}/history")
def get_commit_history(project_id: str, limit: int = Query(20, ge=1, le=100)):
    try:
        p_path = ws_manager._safe_path(project_id)
        git = GitManager(p_path)
        return {"history": git.get_history(limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{project_id}/diff")
def get_git_diff(project_id: str, file_path: Optional[str] = Query(None)):
    try:
        p_path = ws_manager._safe_path(project_id)
        git = GitManager(p_path)
        return {"diff": git.get_diff(file_path=file_path)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
