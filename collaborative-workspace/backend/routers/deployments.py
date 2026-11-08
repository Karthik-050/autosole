from fastapi import APIRouter, HTTPException
from backend.routers.dashboard import deployment_manager, docker_manager

router = APIRouter(prefix="/deployments", tags=["Deployments"])

@router.get("")
def list_deployments():
    return {"deployments": deployment_manager.list_deployments()}

@router.get("/{deployment_id}")
def get_deployment(deployment_id: str):
    dep = deployment_manager.get_deployment(deployment_id)
    if not dep:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return {"deployment": dep}

@router.post("/{deployment_id}/health")
def verify_deployment_health(deployment_id: str):
    dep = deployment_manager.get_deployment(deployment_id)
    if not dep:
        raise HTTPException(status_code=404, detail="Deployment not found")

    health = deployment_manager.check_health(dep["url"])
    new_status = "healthy" if health["healthy"] else "unhealthy"
    deployment_manager.update_status(deployment_id, new_status, log_append=health["message"])
    return {"health": health, "status": new_status}

@router.post("/{deployment_id}/stop")
def stop_deployment(deployment_id: str):
    dep = deployment_manager.get_deployment(deployment_id)
    if not dep:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if dep.get("container_name"):
        docker_manager.stop_container(dep["container_name"])

    deployment_manager.update_status(deployment_id, "stopped", log_append="Container stopped manually by user.")
    return {"message": "Deployment stopped", "deployment": deployment_manager.get_deployment(deployment_id)}
