from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

from backend.config import settings
from backend.routers.dashboard import jenkins_manager, docker_manager

router = APIRouter(prefix="/settings", tags=["Settings"])

class UpdateSettingsRequest(BaseModel):
    jenkins_url: Optional[str] = None
    jenkins_username: Optional[str] = None
    jenkins_api_token: Optional[str] = None
    enforce_mandatory_validation: Optional[bool] = None
    default_deploy_port: Optional[int] = None
    sandbox_image: Optional[str] = None

@router.get("")
def get_settings():
    return {"settings": settings.get_masked_config()}

@router.post("")
def update_settings(req: UpdateSettingsRequest):
    data = req.dict(exclude_unset=True)
    settings.update_config(data)
    return {"settings": settings.get_masked_config(), "message": "Settings updated successfully"}

@router.post("/test-jenkins")
def test_jenkins():
    return {"status": jenkins_manager.get_status()}

@router.post("/test-docker")
def test_docker():
    return {"status": docker_manager.get_status()}
