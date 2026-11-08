from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.routers.dashboard import docker_manager, ws_manager

router = APIRouter(prefix="/docker", tags=["Docker Management"])

class DockerfileRequest(BaseModel):
    content: Optional[str] = None
    project_type: Optional[str] = "python"

class BuildImageRequest(BaseModel):
    tag: str

class RunContainerRequest(BaseModel):
    image_name: str
    container_name: str
    host_port: int
    container_port: Optional[int] = 5000

class ContainerActionRequest(BaseModel):
    container_id: str

@router.get("/status")
def get_docker_status():
    return {"status": docker_manager.get_status()}

@router.get("/images")
def list_images():
    return {"images": docker_manager.list_images()}

@router.get("/containers")
def list_containers():
    return {"containers": docker_manager.list_containers()}

@router.get("/{project_id}/dockerfile")
def get_dockerfile(project_id: str):
    try:
        p_path = ws_manager._safe_path(project_id)
        df_content = docker_manager.get_dockerfile(p_path)
        return {"has_dockerfile": df_content is not None, "content": df_content or ""}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{project_id}/dockerfile")
def save_or_generate_dockerfile(project_id: str, req: DockerfileRequest):
    try:
        p_path = ws_manager._safe_path(project_id)
        if req.content is not None and req.content.strip():
            docker_manager.save_dockerfile(p_path, req.content)
            return {"message": "Dockerfile saved successfully"}
        else:
            docker_manager.generate_dockerfile(p_path, project_type=req.project_type or "python")
            df_content = docker_manager.get_dockerfile(p_path)
            return {"message": "Dockerfile generated successfully", "content": df_content}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{project_id}/build")
def build_project_image(project_id: str, req: BuildImageRequest):
    try:
        p_path = ws_manager._safe_path(project_id)
        result = docker_manager.build_image(p_path, req.tag)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{project_id}/run")
def run_project_container(project_id: str, req: RunContainerRequest):
    try:
        result = docker_manager.run_container(
            image_name=req.image_name,
            container_name=req.container_name,
            host_port=req.host_port,
            container_port=req.container_port or 5000,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/container/stop")
def stop_container(req: ContainerActionRequest):
    return docker_manager.stop_container(req.container_id)

@router.post("/container/remove")
def remove_container(req: ContainerActionRequest):
    return docker_manager.remove_container(req.container_id)
