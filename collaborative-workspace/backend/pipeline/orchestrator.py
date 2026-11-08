import asyncio
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from backend.config import settings
from backend.validation.detector import detect_project
from backend.validation.scanner import CodeValidator
from backend.git.manager import GitManager
from backend.docker.manager import DockerManager
from backend.jenkins.manager import JenkinsManager, sanitize_name
from backend.deployment.manager import DeploymentManager

class PipelineOrchestrator:
    def __init__(self):
        self.runs: Dict[str, Dict[str, Any]] = {}
        self.docker = DockerManager()
        self.jenkins = JenkinsManager()
        self.deployment_mgr = DeploymentManager()

    def get_runs(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        all_runs = list(self.runs.values())
        if project_id:
            all_runs = [r for r in all_runs if r.get("project_id") == project_id]
        return sorted(all_runs, key=lambda r: r.get("started_at", ""), reverse=True)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self.runs.get(run_id)

    async def trigger_pipeline(
        self,
        project_id: str,
        project_path: Path,
        auto_commit: bool = True,
        commit_message: str = "Automated pipeline commit",
        use_jenkins: bool = False,
        build_docker: bool = True,
        deploy_container: bool = True,
        target_port: Optional[int] = None,
        wait: bool = False,
    ) -> Dict[str, Any]:
        """Initiate asynchronous pipeline run."""
        run_id = f"run-{str(uuid.uuid4())[:8]}"
        run_record = {
            "run_id": run_id,
            "project_id": project_id,
            "status": "running",
            "current_stage": "prepare",
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "error": None,
            "stages": [
                {"name": "prepare", "label": "Project Discovery", "status": "pending", "logs": ""},
                {"name": "git_tracking", "label": "Git Version Control", "status": "pending", "logs": ""},
                {"name": "validation", "label": "Code Validation", "status": "pending", "logs": ""},
                {"name": "build", "label": "CI Build & Test", "status": "pending", "logs": ""},
                {"name": "deploy", "label": "Container Deployment", "status": "pending", "logs": ""},
                {"name": "health_check", "label": "Health Verification", "status": "pending", "logs": ""},
            ],
            "artifacts": {},
        }
        self.runs[run_id] = run_record

        workflow_coro = self._execute_workflow(
            run_id=run_id,
            project_id=project_id,
            project_path=project_path,
            auto_commit=auto_commit,
            commit_message=commit_message,
            use_jenkins=use_jenkins,
            build_docker=build_docker,
            deploy_container=deploy_container,
            target_port=target_port or settings.default_deploy_port,
        )

        if wait:
            await workflow_coro
        else:
            asyncio.create_task(workflow_coro)

        return run_record

    async def _execute_workflow(
        self,
        run_id: str,
        project_id: str,
        project_path: Path,
        auto_commit: bool,
        commit_message: str,
        use_jenkins: bool,
        build_docker: bool,
        deploy_container: bool,
        target_port: int,
    ):
        run = self.runs[run_id]

        def update_stage(stage_name: str, status: str, log_msg: str = "", append: bool = True):
            run["current_stage"] = stage_name
            for s in run["stages"]:
                if s["name"] == stage_name:
                    s["status"] = status
                    if log_msg:
                        s["logs"] = (s["logs"] + "\n" + log_msg).strip() if append else log_msg
                    break

        try:
            # ----------------------------------------------------
            # STAGE 1: Prepare & Project Discovery
            # ----------------------------------------------------
            update_stage("prepare", "running", "Analyzing workspace structure and runtime...")
            await asyncio.sleep(0.5)

            project_meta = detect_project(project_path)
            project_type = project_meta["type"]
            update_stage(
                "prepare",
                "success",
                f"Detected runtime: {project_type.upper()} ({project_meta.get('framework') or 'Standard'}). Found {project_meta['files_count']} files."
            )
            run["artifacts"]["project_meta"] = project_meta

            # Ensure Dockerfile exists
            dockerfile = project_path / "Dockerfile"
            if not dockerfile.exists() and project_type != "unknown":
                self.docker.generate_dockerfile(project_path, project_type)
                update_stage("prepare", "success", "Generated default Dockerfile for project runtime.")

            # ----------------------------------------------------
            # STAGE 2: Git Version Control Tracking
            # ----------------------------------------------------
            update_stage("git_tracking", "running", "Checking repository status...")
            await asyncio.sleep(0.4)

            git = GitManager(project_path)
            if not git.is_git_repo():
                git.init_repo()
                update_stage("git_tracking", "running", "Initialized Git repository in workspace.")

            git_status = git.get_status()
            commit_hash = "uncommitted"

            if auto_commit and not git_status["clean"]:
                commit_res = git.commit(commit_message)
                commit_hash = commit_res.get("short_hash", "")
                update_stage(
                    "git_tracking",
                    "success",
                    f"Created Git checkpoint commit: {commit_hash} ('{commit_message}') on branch '{git_status['branch']}'."
                )
            else:
                head = git.get_history(1)
                commit_hash = head[0]["short_hash"] if head else "initial"
                update_stage(
                    "git_tracking",
                    "success",
                    f"Workspace is clean on branch '{git_status['branch']}' (HEAD: {commit_hash})."
                )
            run["artifacts"]["git_commit"] = commit_hash

            # ----------------------------------------------------
            # STAGE 3: Code Validation (Quality Gate)
            # ----------------------------------------------------
            update_stage("validation", "running", "Running AST syntax checks, security audit, and tests...")
            await asyncio.sleep(0.5)

            validator = CodeValidator(project_path)
            scan_result = validator.scan()
            run["artifacts"]["validation"] = scan_result

            val_summary = scan_result["summary"]
            val_log = (
                f"Quality Score: {scan_result['score']}/100\n"
                f"Errors: {val_summary['errors']} | Warnings: {val_summary['warnings']} | Info: {val_summary['info']}"
            )

            # Check Mandatory Validation Policy
            if settings.enforce_mandatory_validation and not scan_result["mandatory_checks_passed"]:
                # QUALITY GATE FAILED -> HALT PIPELINE
                update_stage("validation", "failed", f"{val_log}\n\n[MANDATORY VALIDATION GATE FAILED]: Deployment blocked due to {val_summary['errors']} fatal error(s).")
                for s in run["stages"]:
                    if s["status"] == "pending":
                        s["status"] = "skipped"
                run["status"] = "failed"
                run["error"] = f"Code validation failed with {val_summary['errors']} error(s). Fix code issues before deployment."
                run["finished_at"] = datetime.now().isoformat()
                return

            update_stage(
                "validation",
                "success" if val_summary["errors"] == 0 else "warning",
                f"{val_log}\nValidation checks passed quality gate."
            )

            # ----------------------------------------------------
            # STAGE 4: Build Stage (Jenkins or Local Docker)
            # ----------------------------------------------------
            update_stage("build", "running", "Starting CI build process...")
            safe_name = sanitize_name(project_path.name or "project")
            image_name = f"workspace-{safe_name}:{commit_hash or 'latest'}"
            container_name = f"app-{safe_name}"

            if use_jenkins:
                j_status = self.jenkins.get_status()
                if not j_status["available"]:
                    update_stage(
                        "build",
                        "running",
                        f"Jenkins server offline ({j_status['error']}). Falling back to local Docker build engine..."
                    )
                    use_jenkins = False
                else:
                    pipeline_script = generate_pipeline(safe_name, image_name, container_name, target_port)
                    job_name = f"workspace-{safe_name}"
                    self.jenkins.create_or_update_job(job_name, pipeline_script)
                    trigger_res = self.jenkins.trigger_build(job_name)
                    update_stage(
                        "build",
                        "success",
                        f"Triggered Jenkins job '{job_name}' (Queue #{trigger_res.get('queue_id')})."
                    )

            if not use_jenkins and build_docker:
                d_status = self.docker.get_status()
                if not d_status["available"]:
                    update_stage(
                        "build",
                        "failed",
                        f"Docker engine is unavailable: {d_status['error']}. Please start Docker Desktop."
                    )
                    run["status"] = "failed"
                    run["error"] = "Docker daemon is not running."
                    for s in run["stages"]:
                        if s["status"] == "pending":
                            s["status"] = "skipped"
                    run["finished_at"] = datetime.now().isoformat()
                    return

                build_res = self.docker.build_image(project_path, image_name)
                if not build_res["success"]:
                    update_stage("build", "failed", f"Docker build failed:\n{build_res['stderr']}")
                    run["status"] = "failed"
                    run["error"] = "Docker build failed."
                    for s in run["stages"]:
                        if s["status"] == "pending":
                            s["status"] = "skipped"
                    run["finished_at"] = datetime.now().isoformat()
                    return

                update_stage("build", "success", f"Successfully built Docker image: {image_name}")

            run["artifacts"]["image_name"] = image_name
            run["artifacts"]["container_name"] = container_name

            # ----------------------------------------------------
            # STAGE 5: Container Deployment
            # ----------------------------------------------------
            if deploy_container:
                update_stage("deploy", "running", f"Deploying container '{container_name}' on port {target_port}...")
                await asyncio.sleep(0.5)

                dep_res = self.docker.run_container(
                    image_name=image_name,
                    container_name=container_name,
                    host_port=target_port,
                    container_port=5000 if project_type == "python" else 3000,
                )

                if not dep_res["success"]:
                    update_stage("deploy", "failed", f"Container launch failed: {dep_res.get('error')}")
                    run["status"] = "failed"
                    run["error"] = dep_res.get("error")
                    for s in run["stages"]:
                        if s["status"] == "pending":
                            s["status"] = "skipped"
                    run["finished_at"] = datetime.now().isoformat()
                    return

                update_stage(
                    "deploy",
                    "success",
                    f"Container {container_name} started. Container ID: {dep_res['container_id'][:12]}."
                )
            else:
                update_stage("deploy", "skipped", "Container deployment skipped per configuration.")

            # ----------------------------------------------------
            # STAGE 6: Health Verification
            # ----------------------------------------------------
            if deploy_container:
                update_stage("health_check", "running", f"Verifying HTTP health probe at http://localhost:{target_port}...")
                await asyncio.sleep(2)  # Give container a brief moment to bind port

                url = f"http://localhost:{target_port}"
                health = self.deployment_mgr.check_health(url, timeout=3)

                # Record in deployment manager
                dep_record = self.deployment_mgr.record_deployment(
                    project_id=project_id,
                    project_name=safe_name,
                    image_name=image_name,
                    container_name=container_name,
                    port=target_port,
                    git_commit=commit_hash,
                    validation_status="passed",
                    status="healthy" if health["healthy"] else "unhealthy",
                    logs=f"Health probe: {health['message']}",
                )
                run["artifacts"]["deployment"] = dep_record

                if health["healthy"]:
                    update_stage("health_check", "success", f"Health Check Confirmed: {health['message']} ({url})")
                    run["status"] = "success"
                else:
                    update_stage("health_check", "warning", f"Health Probe Warning: {health['message']}. Container is running.")
                    # Still consider pipeline finished with warning
                    run["status"] = "success"
            else:
                update_stage("health_check", "skipped", "Health check skipped.")
                run["status"] = "success"

        except Exception as e:
            run["status"] = "failed"
            run["error"] = str(e)
            for s in run["stages"]:
                if s["status"] == "running":
                    s["status"] = "failed"
                    s["logs"] = (s["logs"] + f"\nUnhandled exception: {e}").strip()
                elif s["status"] == "pending":
                    s["status"] = "skipped"

        finally:
            run["finished_at"] = datetime.now().isoformat()
