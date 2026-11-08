from pathlib import Path
from typing import Dict, Any, List, Optional

from backend.config import settings
from backend.workspace.manager import WorkspaceManager
from backend.docker.manager import DockerManager
from backend.jenkins.manager import JenkinsManager
from backend.pipeline.orchestrator import PipelineOrchestrator
from backend.deployment.manager import DeploymentManager
from backend.validation.scanner import CodeValidator
from backend.git.manager import GitManager

class DashboardManager:
    def __init__(
        self,
        workspace_mgr: WorkspaceManager,
        docker_mgr: DockerManager,
        jenkins_mgr: JenkinsManager,
        pipeline_mgr: PipelineOrchestrator,
        deploy_mgr: DeploymentManager,
    ):
        self.workspace_mgr = workspace_mgr
        self.docker_mgr = docker_mgr
        self.jenkins_mgr = jenkins_mgr
        self.pipeline_mgr = pipeline_mgr
        self.deploy_mgr = deploy_mgr

    def get_summary(self, active_project_id: Optional[str] = None) -> Dict[str, Any]:
        """Collect real unified dashboard data across all backend subsystems."""
        # 1. Projects
        workspaces = self.workspace_mgr.list_workspaces_detailed()
        active_project = None
        if active_project_id:
            try:
                active_project = self.workspace_mgr.get_workspace_details(active_project_id)
            except Exception:
                pass
        if not active_project and workspaces:
            active_project = workspaces[0]

        # 2. Docker Status
        docker_status = self.docker_mgr.get_status()
        containers = self.docker_mgr.list_containers() if docker_status["available"] else []

        # 3. Jenkins Status
        jenkins_status = self.jenkins_mgr.get_status()
        jenkins_jobs = self.jenkins_mgr.list_jobs() if jenkins_status["available"] else []

        # 4. Active Project Details (Validation + Git)
        validation_data = None
        git_data = None
        if active_project:
            try:
                p_path = Path(active_project["path"])
                validator = CodeValidator(p_path)
                validation_data = validator.scan()
                git = GitManager(p_path)
                git_data = git.get_status()
            except Exception:
                pass

        # 5. Recent Pipeline Runs
        pipeline_runs = self.pipeline_mgr.get_runs(project_id=active_project_id if active_project_id else None)[:5]

        # 6. Deployments
        deployments = self.deploy_mgr.list_deployments()[:5]

        return {
            "projects": {
                "total": len(workspaces),
                "list": workspaces,
                "active": active_project,
            },
            "services": {
                "docker": docker_status,
                "jenkins": jenkins_status,
            },
            "active_project_metrics": {
                "validation": validation_data,
                "git": git_data,
            },
            "recent_pipeline_runs": pipeline_runs,
            "recent_deployments": deployments,
            "containers_summary": {
                "total": len(containers),
                "running": sum(1 for c in containers if c.get("running")),
            },
            "jenkins_jobs_count": len(jenkins_jobs),
        }
