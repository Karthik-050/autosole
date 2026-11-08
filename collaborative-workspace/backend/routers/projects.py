from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

from backend.config import settings
from backend.routers.dashboard import ws_manager

router = APIRouter(prefix="/projects", tags=["Projects"])

class CreateProjectRequest(BaseModel):
    name: Optional[str] = None
    template: Optional[str] = "python"

@router.get("")
def list_projects():
    try:
        return {"projects": ws_manager.list_workspaces_detailed()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
def create_project(req: CreateProjectRequest):
    try:
        wid = ws_manager.create_workspace(name=req.name, template=req.template)
        details = ws_manager.get_workspace_details(wid)
        return {"project": details, "message": "Project created successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{project_id}")
def get_project(project_id: str):
    try:
        return {"project": ws_manager.get_workspace_details(project_id)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{project_id}")
def delete_project(project_id: str):
    try:
        ws_manager.delete_workspace(project_id)
        return {"message": "Project deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/import-automator-test")
def import_automator_test():
    """Import the existing Automator test-project zip into a collaborative workspace."""
    zip_candidates = [
        settings.automator_root / "test-project.zip",
        settings.automator_root / "projects" / "test-project.zip",
        Path("automator/projects/test-project.zip"),
        Path("../automator/projects/test-project.zip"),
    ]

    zip_path = None
    for c in zip_candidates:
        if c.exists():
            zip_path = c
            break

    if not zip_path:
        # Fallback to test-project folder if zip doesn't exist
        folder_candidates = [
            settings.automator_root / "projects" / "test-project",
            Path("automator/projects/test-project"),
        ]
        folder = next((f for f in folder_candidates if f.exists()), None)
        if folder:
            wid = ws_manager.create_workspace(name="Automator Test Project")
            ws_path = ws_manager._safe_path(wid)
            for item in folder.iterdir():
                if item.is_file():
                    ws_manager.write_file(wid, item.name, item.read_text(encoding="utf-8", errors="replace"))
            return {
                "project": ws_manager.get_workspace_details(wid),
                "message": "Automator test project imported successfully",
            }
        raise HTTPException(status_code=404, detail="Automator test project archive not found")

    try:
        wid = ws_manager.import_from_zip(zip_path, project_name="Automator Test Project")
        return {
            "project": ws_manager.get_workspace_details(wid),
            "message": "Automator test project imported successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import project: {e}")
