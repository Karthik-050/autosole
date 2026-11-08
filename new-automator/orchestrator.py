"""Automator End-to-End Build and Deployment Pipeline Orchestrator.

Coordinates Git repository retrieval, stack analysis, Dockerfile generation,
Jenkins pipeline execution (or local fallback), candidate health validation,
and zero-downtime deployment.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import traceback
from typing import Any, Dict, Optional

from analyzer.detector import DetectionResult, detect_project
from config import get_settings
import database
from deployment.manager import DeploymentManager, DeploymentResult
from docker.generator import build_image, generate_dockerfile
from git_integration.repository import GitRepository
from jenkins_automation import client as jenkins_client
from jenkins_automation.job_generator import generate_pipeline, sanitize_name

logger = logging.getLogger(__name__)


# ============================================================
# BUILD ORCHESTRATOR
# ============================================================

class BuildOrchestrator:
    """Coordinates the full CI/CD lifecycle for a repository build."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.git_repo = GitRepository(self.settings.REPOS_DIR, timeout=self.settings.GIT_TIMEOUT)
        self.deployment_mgr = DeploymentManager(
            health_check_timeout=self.settings.HEALTH_CHECK_TIMEOUT,
            retention_count=self.settings.BUILD_RETENTION_COUNT,
        )
        self._semaphore = asyncio.Semaphore(self.settings.MAX_CONCURRENT_BUILDS)

    async def execute_build(
        self,
        repository_id: str,
        build_id: str,
        branch: Optional[str] = None,
        commit_sha: Optional[str] = None,
        trigger_type: str = "manual",
        pr_number: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run the end-to-end pipeline asynchronously with concurrency limiting."""
        async with self._semaphore:
            return await self._run_pipeline(
                repository_id=repository_id,
                build_id=build_id,
                requested_branch=branch,
                requested_commit_sha=commit_sha,
                trigger_type=trigger_type,
                pr_number=pr_number,
            )

    async def _run_pipeline(
        self,
        repository_id: str,
        build_id: str,
        requested_branch: Optional[str],
        requested_commit_sha: Optional[str],
        trigger_type: str,
        pr_number: Optional[int],
    ) -> Dict[str, Any]:
        """Internal pipeline execution sequence."""
        start_time = datetime.now(timezone.utc)
        log_file = self.settings.LOGS_DIR / f"{build_id}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        def _log(msg: str) -> None:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            line = f"[{ts}] {msg}\n"
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass
            logger.info("[%s] %s", build_id[:8], msg)

        _log(f"Starting build pipeline for repository {repository_id} (trigger: {trigger_type})")

        # Step 1: Fetch repository metadata
        repo = await database.get_repository(repository_id)
        if not repo:
            _log(f"ERROR: Repository {repository_id} not found in database.")
            await database.update_build(
                build_id,
                status="failed",
                error_message="Repository not found in database",
                completed_at=database.utc_now_iso(),
            )
            return {"success": False, "error": "Repository not found"}

        branch = requested_branch or repo.get("default_branch") or "main"
        clone_url = repo["url"]
        credential_token = repo.get("credential_id") or os.environ.get("AUTOMATOR_GIT_TOKEN")

        await database.update_build(
            build_id,
            status="running",
            started_at=start_time.isoformat(),
            branch=branch,
            log_path=str(log_file),
        )

        workspace_path: Optional[Path] = None

        try:
            # Step 2: Clone or fetch bare repository
            _log(f"Fetching repository from {clone_url}...")
            self.git_repo.clone_or_fetch(
                clone_url=clone_url,
                repo_id=repository_id,
                credential_token=credential_token,
            )

            # Step 3: Check out isolated build workspace
            _log(f"Checking out workspace for branch '{branch}' (commit: {requested_commit_sha or 'HEAD'})...")
            clone_result = self.git_repo.checkout_build_workspace(
                repo_id=repository_id,
                build_id=build_id,
                branch=branch,
                commit_sha=requested_commit_sha,
            )
            workspace_path = clone_result.repo_path
            commit = clone_result.commit

            _log(f"Checked out commit {commit.short_sha}: '{commit.message}' by {commit.author}")
            await database.update_build(
                build_id,
                commit_sha=commit.sha,
                commit_message=commit.message,
            )

            # Step 4: Automatic Stack Detection
            _log("Analyzing project technology stack and dependencies...")
            detection: DetectionResult = detect_project(workspace_path)
            _log(
                f"Detected stack: language={detection.language} (v{detection.language_version}), "
                f"framework={detection.framework}, manager={detection.dependency_manager}, "
                f"port={detection.port}"
            )
            if detection.warnings:
                for w in detection.warnings:
                    _log(f"Warning: {w}")

            await database.update_build(
                build_id,
                detected_stack=detection.to_dict(),
            )

            if detection.language == "unknown" and detection.confidence == 0:
                raise RuntimeError(
                    "Stack analyzer could not determine project technology. "
                    "Ensure supported dependency files (requirements.txt, package.json, pom.xml, build.gradle, go.mod) exist."
                )

            # Step 5: Generate or validate Dockerfile
            _log("Validating or generating Dockerfile...")
            dockerfile_source = "user" if detection.has_existing_dockerfile and detection.existing_dockerfile_valid else "generated"
            dockerfile_path = generate_dockerfile(
                workspace_path,
                detection,
                force_regenerate=False,
            )
            _log(f"Dockerfile ready ({dockerfile_source}): {dockerfile_path}")
            await database.update_build(
                build_id,
                dockerfile_source=dockerfile_source,
            )

            # Step 6: Execute Build & Tests (Jenkins or Local Engine)
            safe_repo_name = sanitize_name(repo["name"])
            image_tag = f"automator-{safe_repo_name}:{build_id[:8]}"
            await database.update_build(build_id, docker_image_tag=image_tag)

            # Check if Jenkins is active and connected
            jenkins_server = None
            if self.settings.JENKINS_USERNAME and self.settings.JENKINS_API_TOKEN:
                jenkins_server = jenkins_client.connect_to_jenkins(
                    self.settings.JENKINS_URL,
                    self.settings.JENKINS_USERNAME,
                    self.settings.JENKINS_API_TOKEN,
                )

            if jenkins_server and jenkins_client.check_jenkins_healthy(jenkins_server):
                _log("Jenkins controller is reachable. Running pipeline via Jenkins...")
                job_name = repo.get("jenkins_job_name") or f"automator-{safe_repo_name}"
                workspace_rel = f"workspaces/{repository_id}/{build_id}"

                pipeline_script = generate_pipeline(
                    project_name=safe_repo_name,
                    image_name=image_tag,
                    container_name=f"automator-{safe_repo_name}",
                    container_port=detection.port,
                    detection_result=detection,
                    git_url=clone_url,
                    branch=branch,
                    commit_sha=commit.sha,
                    workspace_rel_path=workspace_rel,
                    health_check_path=detection.health_check_path,
                    test_command=detection.test_command,
                    build_command=detection.build_command,
                    host_port=self.settings.DEFAULT_HOST_PORT,
                    candidate_port=self.settings.CANDIDATE_HOST_PORT,
                )

                jenkins_client.create_job(jenkins_server, job_name, pipeline_script)
                queue_id = jenkins_client.trigger_job(jenkins_server, job_name)
                _log(f"Jenkins job '{job_name}' queued with Queue ID {queue_id}")

                await database.update_build(
                    build_id,
                    jenkins_queue_id=queue_id,
                )

                # Wait for build number from queue
                build_num = await asyncio.to_thread(
                    jenkins_client.get_build_from_queue,
                    jenkins_server,
                    queue_id,
                    timeout=60,
                )
                if build_num:
                    _log(f"Jenkins build #{build_num} started. Monitoring...")
                    await database.update_build(
                        build_id,
                        jenkins_build_number=build_num,
                    )
                    build_info = await asyncio.to_thread(
                        jenkins_client.wait_for_build_completion,
                        jenkins_server,
                        job_name,
                        build_num,
                        timeout=self.settings.DOCKER_BUILD_TIMEOUT,
                    )
                    jenkins_logs = await asyncio.to_thread(
                        jenkins_client.get_build_console_output,
                        jenkins_server,
                        job_name,
                        build_num,
                    )
                    _log(f"--- Jenkins Console Output ---:\n{jenkins_logs}")

                    result_status = (build_info or {}).get("result")
                    if result_status != "SUCCESS":
                        raise RuntimeError(f"Jenkins pipeline build failed with status: {result_status}")
            else:
                # Local execution engine fallback
                _log("Running test suite locally...")
                if detection.test_command:
                    _log(f"Executing: {detection.test_command}")
                    proc = await asyncio.create_subprocess_shell(
                        detection.test_command,
                        cwd=str(workspace_path),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate()
                    std_out = stdout.decode("utf-8", errors="ignore")
                    err_out = stderr.decode("utf-8", errors="ignore")
                    _log(std_out)
                    if err_out:
                        _log(err_out)

                    combined = f"{std_out}\n{err_out}".strip()
                    if proc.returncode != 0:
                        # In Python unittest, code 5 means 'NO TESTS RAN'. Only fail if actual tests failed or non-test error
                        if "FAIL" in combined or "ERROR" in combined or "AssertionError" in combined or "NO TESTS RAN" not in combined:
                            _log(f"Tests failed (code {proc.returncode}):\n{combined}")
                            raise RuntimeError(f"Automated test suite failed: {combined}")
                        else:
                            _log("No unit test cases discovered in workspace. Proceeding.")
                    else:
                        _log("All automated tests passed successfully.")

                _log(f"Building Docker image: {image_tag}...")
                await asyncio.to_thread(
                    build_image,
                    workspace_path,
                    image_tag,
                    timeout=self.settings.DOCKER_BUILD_TIMEOUT,
                )
                _log("Docker image built successfully.")

            # Step 7: Zero-Downtime Deployment
            _log("Starting candidate container for zero-downtime deployment...")
            deploy_result: DeploymentResult = await self.deployment_mgr.deploy_candidate(
                repo_id=repository_id,
                build_id=build_id,
                image_tag=image_tag,
                container_port=detection.port,
                health_check_path=detection.health_check_path,
            )

            if not deploy_result.success:
                raise RuntimeError(f"Candidate container health check failed: {deploy_result.error_message}")

            _log(
                f"Candidate deployment succeeded! Traffic switched to {deploy_result.container_name} "
                f"on host port {deploy_result.host_port}. Preview URL: {deploy_result.preview_url}"
            )
            if deploy_result.previous_container_stopped:
                _log(f"Previous preview container drained and stopped: {deploy_result.previous_container_stopped}")

            # Mark build as success!
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            await database.update_build(
                build_id,
                status="success",
                health_check_passed=True,
                container_id=deploy_result.container_name,
                completed_at=end_time.isoformat(),
                duration_seconds=duration,
            )
            _log(f"Pipeline finished successfully in {duration:.1f}s.")
            return {
                "success": True,
                "build_id": build_id,
                "preview_url": deploy_result.preview_url,
                "direct_url": deploy_result.direct_url,
                "host_port": deploy_result.host_port,
            }

        except Exception as exc:
            err_msg = str(exc)
            _log(f"PIPELINE FAILURE: {err_msg}")
            _log(traceback.format_exc())

            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            await database.update_build(
                build_id,
                status="failed",
                error_message=err_msg,
                completed_at=end_time.isoformat(),
                duration_seconds=duration,
            )
            return {"success": False, "error": err_msg}

        finally:
            # Clean up ephemeral checkout workspace if configured
            if workspace_path and workspace_path.exists():
                try:
                    self.git_repo.cleanup_workspace(workspace_path)
                except Exception as exc:
                    logger.debug("Failed to clean up workspace %s: %s", workspace_path, exc)
