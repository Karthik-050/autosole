from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from backend.workspace.manager import WorkspaceManager
from backend.docker.manager import DockerManager
from backend.jenkins.manager import JenkinsManager
from backend.pipeline.orchestrator import PipelineOrchestrator
from backend.deployment.manager import DeploymentManager
from backend.dashboard.manager import DashboardManager

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# Subsystem singletons
ws_manager = WorkspaceManager()
docker_manager = DockerManager()
jenkins_manager = JenkinsManager()
pipeline_manager = PipelineOrchestrator()
deployment_manager = DeploymentManager()
dashboard_manager = DashboardManager(
    workspace_mgr=ws_manager,
    docker_mgr=docker_manager,
    jenkins_mgr=jenkins_manager,
    pipeline_mgr=pipeline_manager,
    deploy_mgr=deployment_manager,
)

@router.get("/stats")
def get_dashboard_stats(project_id: Optional[str] = Query(None)):
    try:
        return dashboard_manager.get_summary(active_project_id=project_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
