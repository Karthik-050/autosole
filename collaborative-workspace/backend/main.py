from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.routers.dashboard import (
    router as dashboard_router,
    ws_manager as manager,
)
from backend.routers.projects import router as projects_router
from backend.routers.git import router as git_router
from backend.routers.validation import router as validation_router
from backend.routers.docker import router as docker_router
from backend.routers.jenkins import router as jenkins_router
from backend.routers.pipeline import router as pipeline_router
from backend.routers.deployments import router as deployments_router
from backend.routers.settings import router as settings_router
from backend.routers.webhooks import router as webhooks_router

app = FastAPI(
    title="Unified Automator & Collaborative Workspace API",
    version="2.0.0",
    description="Integrated platform for collaborative development, code validation, git version control, Docker management, Jenkins automation, and deployments."
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- INCLUDE MODULAR API ROUTERS -----------------
app.include_router(dashboard_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(git_router, prefix="/api")
app.include_router(validation_router, prefix="/api")
app.include_router(docker_router, prefix="/api")
app.include_router(jenkins_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(deployments_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(webhooks_router, prefix="/api")


from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

# ----------------- BASE HEALTH CHECK / UI SERVING -----------------
@app.get("/")
def home(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept and (DIST_DIR / "index.html").exists():
        return FileResponse(DIST_DIR / "index.html")

    return {
        "message": "Unified Automator & Collaborative Workspace API is running",
        "version": "2.0.0",
        "endpoints": {
            "dashboard": "/api/dashboard/stats",
            "projects": "/api/projects",
            "git": "/api/git/{project_id}/status",
            "validation": "/api/validation/{project_id}/scan",
            "docker": "/api/docker/status",
            "jenkins": "/api/jenkins/status",
            "pipeline": "/api/pipeline/runs",
            "github_webhook": "/api/webhooks/github",
            "deployments": "/api/deployments",
            "settings": "/api/settings",
            "docs": "/docs"
        }
    }


# ==============================================================
# BACKWARD COMPATIBILITY: EXISTING WORKSPACE API CONTRACTS
# ==============================================================

@app.post("/workspaces")
def create_workspace():
    wid = manager.create_workspace()
    return {
        "workspace_id": wid,
        "message": "Workspace created successfully"
    }


@app.get("/workspaces")
def list_workspaces():
    return {
        "workspaces": manager.list_workspaces()
    }


@app.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str):
    try:
        manager.delete_workspace(workspace_id)
        return {"message": "Workspace deleted"}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------- FILE OPERATIONS ----------------

@app.post("/workspaces/{workspace_id}/files")
def create_file(workspace_id: str, filename: str):
    try:
        manager.create_file(workspace_id, filename)
        return {"message": "File created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/workspaces/{workspace_id}/files")
def list_files(workspace_id: str):
    try:
        files = manager.list_files(workspace_id)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/workspaces/{workspace_id}/write")
def write_file(workspace_id: str, filename: str, content: str):
    try:
        manager.write_file(workspace_id, filename, content)
        return {"message": "File written successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/workspaces/{workspace_id}/read")
def read_file(workspace_id: str, filename: str):
    try:
        content = manager.read_file(workspace_id, filename)
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/workspaces/{workspace_id}/files")
def delete_file(workspace_id: str, filename: str):
    try:
        manager.delete_file(workspace_id, filename)
        return {"message": "File deleted"}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------- SANDBOX RUNNER ----------------

@app.post("/workspaces/{workspace_id}/run")
def run_file(workspace_id: str, filename: str):
    try:
        result = manager.run_file(workspace_id, filename)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
