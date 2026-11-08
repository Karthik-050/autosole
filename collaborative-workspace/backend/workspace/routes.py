from fastapi import APIRouter
from .manager import WorkspaceManager

router = APIRouter()
manager = WorkspaceManager()

@router.post("/workspace")
def create_workspace():
    wid = manager.create_workspace()
    return {"workspace_id": wid}

@router.get("/workspace")
def list_workspaces():
    return manager.list_workspaces()