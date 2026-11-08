"""Automator CI/CD FastAPI Server and REST API.

Provides API routes for repository management, project ZIP uploads,
pipeline builds, logs, GitHub webhook automation, preview reverse proxy, and web UI.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import shutil
import tempfile
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from analyzer.detector import detect_project
from config import get_settings
import database
from deployment.diagnostics import get_preview_diagnostics
from deployment.proxy import proxy_preview_request
from docker.generator import generate_dockerfile
from git_integration.repository import GitRepository
from git_integration.validators import (
    sanitize_repo_name,
    validate_branch_name,
    validate_commit_sha,
    validate_git_url,
)
from git_integration.webhook import parse_webhook_event, verify_webhook_signature
from orchestrator import BuildOrchestrator
from project_manager import extract_project

logger = logging.getLogger(__name__)
settings = get_settings()
orchestrator = BuildOrchestrator()
TEMPLATES_DIR = settings.BASE_DIR / "templates"


# ============================================================
# LIFESPAN CONTEXT
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize database and resources on application startup."""
    logger.info("Initializing Automator database at %s...", settings.DB_PATH)
    await database.init_db(settings.DB_PATH)
    logger.info("Database initialized successfully.")
    yield


app = FastAPI(
    title="Automator CI/CD",
    description="Git & ZIP CI/CD with Jenkins, Stack Detection, Docker Generation, and Zero-Downtime Deployment",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# PYDANTIC SCHEMAS
# ============================================================

class RepositoryCreateRequest(BaseModel):
    url: str = Field(..., description="HTTPS clone URL of Git repository")
    default_branch: str = Field(default="main", description="Default branch")
    credential_token: Optional[str] = Field(default=None, description="Access token for private repository")
    webhook_secret: Optional[str] = Field(default=None, description="Custom webhook secret")


class RepositoryUpdateRequest(BaseModel):
    default_branch: Optional[str] = None
    credential_id: Optional[str] = None
    webhook_secret: Optional[str] = None
    jenkins_job_name: Optional[str] = None
    status: Optional[str] = None


class TriggerBuildRequest(BaseModel):
    branch: Optional[str] = None
    commit_sha: Optional[str] = None


def _public_repository(repository: Dict[str, Any]) -> Dict[str, Any]:
    """Remove stored credentials and webhook secrets from API responses."""
    public = dict(repository)
    credential_configured = bool(public.pop("credential_id", None))
    webhook_secret_configured = bool(public.pop("webhook_secret", None))
    public["credential_configured"] = credential_configured
    public["webhook_secret_configured"] = webhook_secret_configured
    return public


# ============================================================
# WEB UI ROUTE
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def get_index() -> HTMLResponse:
    """Serve the Web Dashboard interface."""
    index_file = TEMPLATES_DIR / "index.html"
    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    return HTMLResponse("<h1>Automator CI/CD</h1><p>Web UI template not found.</p>")


# ============================================================
# PROJECT ZIP UPLOAD API
# ============================================================

@app.post("/api/projects/upload", status_code=status.HTTP_201_CREATED)
@app.post("/projects/upload", status_code=status.HTTP_201_CREATED)
async def upload_project_zip(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Accept project ZIP archive upload, extract project, detect stack, and generate Dockerfile."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are supported.")

    temp_dir = Path(tempfile.mkdtemp(prefix="automator_upload_"))
    temp_zip = temp_dir / file.filename

    try:
        with open(temp_zip, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Extract project using robust project_manager
        project_path = extract_project(temp_zip)
        detection = detect_project(project_path)
        dockerfile_path = generate_dockerfile(project_path, detection)

        return {
            "success": True,
            "filename": file.filename,
            "project_name": project_path.name,
            "project_path": str(project_path),
            "dockerfile_path": str(dockerfile_path),
            "detection": detection.to_dict(),
        }
    except Exception as exc:
        logger.error("Failed to process uploaded project ZIP: %s", exc)
        raise HTTPException(status_code=400, detail=f"Failed to process project ZIP: {exc}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ============================================================
# REPOSITORY REST API
# ============================================================

@app.post("/repositories", status_code=status.HTTP_201_CREATED)
async def connect_repository(payload: RepositoryCreateRequest) -> Dict[str, Any]:
    """Connect a new Git repository."""
    try:
        parsed = validate_git_url(payload.url, allowed_providers=settings.ALLOWED_GIT_PROVIDERS)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        clean_branch = validate_branch_name(payload.default_branch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    git_repo = GitRepository(settings.REPOS_DIR)
    repo_id = git_repo.generate_repo_id(parsed.clone_url)

    # Check if already connected
    existing = await database.get_repository(repo_id)
    if existing:
        return _public_repository(existing)

    # Validate access
    is_accessible = git_repo.validate_access(parsed.clone_url, credential_token=payload.credential_token)
    if not is_accessible and payload.credential_token:
        raise HTTPException(
            status_code=400,
            detail="Could not access private repository. Check credentials or repository URL.",
        )

    webhook_sec = payload.webhook_secret or settings.GITHUB_WEBHOOK_SECRET
    safe_name = sanitize_repo_name(parsed.repo_name)
    jenkins_job = f"automator-{safe_name}"

    repo_record = await database.create_repository(
        url=parsed.original_url,
        provider=parsed.provider,
        name=parsed.repo_name,
        owner=parsed.owner,
        default_branch=clean_branch,
        is_private=bool(payload.credential_token),
        credential_id=payload.credential_token,
        webhook_secret=webhook_sec,
        jenkins_job_name=jenkins_job,
        repo_id=repo_id,
        status="active",
    )
    return _public_repository(repo_record)


@app.get("/repositories")
async def list_repositories(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """List connected Git repositories."""
    repositories = await database.list_repositories(limit=limit, offset=offset)
    return [_public_repository(repository) for repository in repositories]


@app.get("/repositories/{repository_id}")
async def get_repository_details(repository_id: str) -> Dict[str, Any]:
    """Retrieve repository metadata and latest pipeline result."""
    repo = await database.get_repository(repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    latest_build = await database.get_latest_successful_build(repository_id)
    current_deployment = await database.get_current_deployment(repository_id)

    res = _public_repository(repo)
    res["latest_successful_build"] = latest_build
    res["current_deployment"] = current_deployment
    return res


@app.patch("/repositories/{repository_id}")
async def update_repository_settings(repository_id: str, payload: RepositoryUpdateRequest) -> Dict[str, Any]:
    """Update repository configuration."""
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_data:
        repo = await database.get_repository(repository_id)
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found")
        return _public_repository(repo)

    try:
        updated = await database.update_repository(repository_id, **update_data)
        if not updated:
            raise HTTPException(status_code=404, detail="Repository not found")
        return _public_repository(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/repositories/{repository_id}")
async def disconnect_repository(repository_id: str) -> Dict[str, Any]:
    """Disconnect repository from Automator."""
    deleted = await database.delete_repository(repository_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Repository not found")
    return {"success": True, "message": f"Repository {repository_id} disconnected."}


@app.post("/repositories/{repository_id}/sync")
async def sync_repository(repository_id: str) -> Dict[str, Any]:
    """Fetch updates from remote repository."""
    repo = await database.get_repository(repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    git_repo = GitRepository(settings.REPOS_DIR)
    try:
        git_repo.clone_or_fetch(
            clone_url=repo["url"],
            repo_id=repository_id,
            credential_token=repo.get("credential_id"),
        )
        branches = git_repo.get_branches(repository_id)
        default_branch = git_repo.get_default_branch(repository_id)
        return {"success": True, "branches": branches, "default_branch": default_branch}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Git sync failed: {exc}")


# ============================================================
# BUILD PIPELINE REST API
# ============================================================

@app.post("/repositories/{repository_id}/builds", status_code=status.HTTP_202_ACCEPTED)
async def trigger_build(
    repository_id: str,
    background_tasks: BackgroundTasks,
    payload: Optional[TriggerBuildRequest] = None,
) -> Dict[str, Any]:
    """Trigger a pipeline build for a repository."""
    repo = await database.get_repository(repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    branch = (payload.branch if payload and payload.branch else None) or repo.get("default_branch") or "main"
    commit_sha = payload.commit_sha if payload and payload.commit_sha else None

    build = await database.create_build(
        repository_id=repository_id,
        commit_sha=commit_sha or "HEAD",
        branch=branch,
        trigger_type="manual",
        status="queued",
    )

    background_tasks.add_task(
        orchestrator.execute_build,
        repository_id=repository_id,
        build_id=build["id"],
        branch=branch,
        commit_sha=commit_sha,
        trigger_type="manual",
    )

    return build


@app.get("/repositories/{repository_id}/builds")
async def list_repository_builds(
    repository_id: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List build history for a repository."""
    return await database.list_builds(repo_id=repository_id, limit=limit, offset=offset)


@app.get("/builds/{build_id}")
async def get_build_status(build_id: str) -> Dict[str, Any]:
    """Get details and status of a specific build."""
    build = await database.get_build(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    return build


@app.get("/builds/{build_id}/logs")
async def get_build_logs(build_id: str) -> Dict[str, Any]:
    """Retrieve captured console logs for a build."""
    build = await database.get_build(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    log_path = build.get("log_path") or str(settings.LOGS_DIR / f"{build_id}.log")
    p = Path(log_path)
    logs = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else "No log output available."

    return {
        "build_id": build_id,
        "status": build.get("status"),
        "logs": logs,
    }


@app.get("/builds/{build_id}/reports")
async def get_build_reports(build_id: str) -> Dict[str, Any]:
    """Get technology detection and test reports for a build."""
    build = await database.get_build(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    return {
        "build_id": build_id,
        "detected_stack": build.get("detected_stack"),
        "test_summary": build.get("test_summary"),
        "health_check_passed": build.get("health_check_passed"),
    }


@app.post("/builds/{build_id}/rollback")
async def rollback_to_build(build_id: str) -> Dict[str, Any]:
    """Roll back active preview deployment to this build's image."""
    build = await database.get_build(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    repo_id = build["repository_id"]
    res = await orchestrator.deployment_mgr.rollback(repo_id=repo_id)
    if not res.success:
        raise HTTPException(status_code=400, detail=res.error_message)

    return {
        "success": True,
        "message": f"Rollback succeeded. Preview active on port {res.host_port}.",
        "preview_url": res.preview_url,
    }


# ============================================================
# WEBHOOK API & STATUS
# ============================================================

@app.get("/repositories/{repository_id}/webhook-status")
async def get_webhook_status(repository_id: str) -> Dict[str, Any]:
    """Get webhook configuration and recent delivery status."""
    repo = await database.get_repository(repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    deliveries = await database.list_webhook_deliveries(repo_id=repository_id, limit=5)
    return {
        "repository_id": repository_id,
        "webhook_url": "/webhooks/github",
        "webhook_secret_configured": bool(repo.get("webhook_secret") or settings.GITHUB_WEBHOOK_SECRET),
        "recent_deliveries": deliveries,
    }


@app.post("/api/webhooks/github")
async def forward_workspace_github_webhook(request: Request) -> Response:
    """Forward a separate public webhook delivery to the local Workspace app."""
    if not request.headers.get("x-hub-signature-256"):
        raise HTTPException(status_code=401, detail="Missing webhook signature.")

    body = await request.body()
    headers = {
        header: request.headers[header]
        for header in (
            "content-type",
            "x-github-delivery",
            "x-github-event",
            "x-hub-signature-256",
        )
        if request.headers.get(header)
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            upstream = await client.post(
                settings.COLLABORATIVE_WORKSPACE_WEBHOOK_URL,
                content=body,
                headers=headers,
            )
    except httpx.RequestError as exc:
        logger.warning("Collaborative Workspace webhook endpoint is unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Collaborative Workspace webhook endpoint is unavailable.",
        ) from exc

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


@app.post("/webhooks/github")
async def handle_github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
) -> Response:
    """Handle incoming GitHub webhooks (push and pull_request events)."""
    if not x_github_delivery or not x_github_event:
        raise HTTPException(status_code=400, detail="Missing required GitHub webhook headers.")

    raw_body = await request.body()

    # Deduplication check
    existing_delivery = await database.get_webhook_delivery(x_github_delivery)
    if existing_delivery and existing_delivery.get("processed"):
        logger.info("Ignoring duplicate webhook delivery: %s", x_github_delivery)
        return JSONResponse(status_code=200, content={"status": "already_processed", "delivery_id": x_github_delivery})

    # Decode JSON payload
    try:
        payload_data = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    repo_data = payload_data.get("repository") or {}
    clone_url = repo_data.get("clone_url") or repo_data.get("html_url") or ""
    repo_name = repo_data.get("name")
    repo_owner = (repo_data.get("owner") or {}).get("login") or (repo_data.get("owner") or {}).get("name")

    matched_repo = None
    if clone_url:
        matched_repo = await database.get_repository_by_url(clone_url)
    if not matched_repo and repo_owner and repo_name:
        matched_repo = await database.get_repository_by_name(repo_owner, repo_name)

    # Signature verification
    expected_secret = matched_repo.get("webhook_secret") if matched_repo else settings.GITHUB_WEBHOOK_SECRET
    if not x_hub_signature_256:
        logger.warning("Rejected webhook delivery %s without a signature.", x_github_delivery)
        raise HTTPException(status_code=401, detail="Missing webhook signature.")

    is_valid_sig = verify_webhook_signature(raw_body, x_hub_signature_256, expected_secret)
    if not is_valid_sig:
        logger.warning("Rejected webhook delivery %s due to invalid signature.", x_github_delivery)
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    if not matched_repo:
        logger.info("Webhook received for untracked repository: %s/%s", repo_owner, repo_name)
        return JSONResponse(status_code=200, content={"status": "untracked_repository", "repo": f"{repo_owner}/{repo_name}"})

    parsed_event = parse_webhook_event(x_github_event, payload_data, x_github_delivery)
    if not parsed_event:
        return JSONResponse(status_code=200, content={"status": "ignored_event_or_ref", "event": x_github_event})

    await database.create_webhook_delivery(
        delivery_id=x_github_delivery,
        repository_id=matched_repo["id"],
        event_type=parsed_event.event_type,
        action=parsed_event.action,
        commit_sha=parsed_event.commit_sha,
        branch=parsed_event.branch,
        pr_number=parsed_event.pr_number,
        payload_summary={
            "author": parsed_event.author,
            "message": parsed_event.commit_message,
            "title": parsed_event.pr_title,
        },
    )

    build = await database.create_build(
        repository_id=matched_repo["id"],
        commit_sha=parsed_event.commit_sha,
        branch=parsed_event.branch,
        commit_message=parsed_event.commit_message,
        trigger_type=parsed_event.event_type,
        pr_number=parsed_event.pr_number,
        status="queued",
    )

    await database.mark_webhook_processed(x_github_delivery, build_id=build["id"])

    background_tasks.add_task(
        orchestrator.execute_build,
        repository_id=matched_repo["id"],
        build_id=build["id"],
        branch=parsed_event.branch,
        commit_sha=parsed_event.commit_sha,
        trigger_type=parsed_event.event_type,
        pr_number=parsed_event.pr_number,
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "queued",
            "delivery_id": x_github_delivery,
            "build_id": build["id"],
            "repository": matched_repo["name"],
            "branch": parsed_event.branch,
            "commit_sha": parsed_event.commit_sha,
        },
    )


# ============================================================
# PREVIEW DIAGNOSTICS REST API
# ============================================================

@app.get("/api/diagnostics/preview/{preview_id}")
async def get_preview_diagnostics_api(preview_id: str) -> Dict[str, Any]:
    """Return runtime diagnostics for preview proxy, Docker container, and ports."""
    return await get_preview_diagnostics(preview_id)


# ============================================================
# ZERO-DOWNTIME PREVIEW REVERSE PROXY
# ============================================================

@app.api_route("/preview/{repository_id}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@app.api_route("/preview/{repository_id}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def preview_reverse_proxy(repository_id: str, path: str = "", request: Request = None) -> Response:
    """Dynamic zero-downtime reverse proxy to the currently healthy preview container."""
    return await proxy_preview_request(repository_id, path, request)
