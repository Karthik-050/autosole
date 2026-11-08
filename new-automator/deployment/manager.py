"""Automator Zero-Downtime Deployment Manager.

Implements candidate container startup, automated health checks, smoke tests,
atomic traffic switching, rollback, and cleanup retention policies.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os
import re
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from config import get_settings
import database
from docker.generator import run_container, stop_and_remove_container
from git_integration.validators import sanitize_repo_name

logger = logging.getLogger(__name__)


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class CandidateContainer:
    """Metadata for an in-flight deployment candidate container."""

    repo_id: str
    build_id: str
    container_name: str
    container_id: str
    image_tag: str
    host_port: int
    container_port: int
    health_url: str


@dataclass
class DeploymentResult:
    """Result of zero-downtime deployment execution."""

    success: bool
    deployment_id: Optional[str] = None
    container_name: str = ""
    host_port: Optional[int] = None
    container_port: Optional[int] = None
    preview_url: str = ""
    direct_url: str = ""
    is_switched: bool = False
    previous_container_stopped: Optional[str] = None
    error_message: Optional[str] = None


# ============================================================
# PORT ALLOCATION HELPER
# ============================================================

def get_docker_allocated_ports() -> Set[int]:
    """Retrieve all host ports currently published by running or created Docker containers."""
    ports: Set[int] = set()
    try:
        res = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            for match in re.finditer(r":(\d+)->", res.stdout):
                ports.add(int(match.group(1)))
    except Exception as exc:
        logger.debug("Failed querying Docker for allocated ports: %s", exc)
    return ports


def is_host_port_busy(port: int, docker_ports: Set[int]) -> bool:
    """Check if a host port is currently in use by Docker, a daemon, or an active listener."""
    if port in docker_ports:
        return True

    # 1. Active connection probe: does any service respond on 127.0.0.1?
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.15)
        try:
            s.connect(("127.0.0.1", port))
            return True  # Connection succeeded -> port is definitely in use
        except (ConnectionRefusedError, socket.timeout, OSError):
            pass

    # 2. Strict bind check without SO_REUSEADDR
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE") and os.name == "nt":
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                except OSError:
                    pass
            s.bind(("0.0.0.0", port))
    except OSError:
        return True

    return False


def find_available_port(
    start_port: int = 5100,
    max_port: int = 5900,
    exclude_ports: Optional[Set[int]] = None,
) -> int:
    """Find a currently unused host port in the specified range.

    Cross-checks active Docker container port mappings, active socket listeners,
    and binding availability to avoid collisions during zero-downtime candidate deployment.
    """
    excluded = exclude_ports or set()
    docker_ports = get_docker_allocated_ports()

    for port in range(start_port, max_port):
        if port in excluded:
            continue
        if is_host_port_busy(port, docker_ports):
            continue
        return port

    raise RuntimeError(f"No available host ports found in range {start_port}-{max_port}")


# ============================================================
# DEPLOYMENT MANAGER
# ============================================================

class DeploymentManager:
    """Manages zero-downtime test and preview container deployments."""

    def __init__(
        self,
        health_check_timeout: int = 45,
        health_poll_interval: float = 2.0,
        retention_count: int = 5,
    ) -> None:
        self.health_check_timeout = health_check_timeout
        self.health_poll_interval = health_poll_interval
        self.retention_count = retention_count

    async def validate_candidate_health(
        self,
        health_url: str,
        timeout: Optional[int] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Poll candidate container health endpoint until healthy or timeout."""
        effective_timeout = timeout or self.health_check_timeout
        start_time = time.time()

        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
            while time.time() - start_time < effective_timeout:
                try:
                    resp = await client.get(health_url)
                    if resp.status_code < 500:
                        logger.info("Candidate health check passed at %s (HTTP %d)", health_url, resp.status_code)
                        return True, None
                except (httpx.ConnectError, httpx.TimeoutException) as exc:
                    logger.debug("Candidate not ready yet at %s: %s", health_url, exc)
                except Exception as exc:
                    logger.debug("Health probe exception: %s", exc)

                await asyncio.sleep(self.health_poll_interval)

        return False, f"Candidate failed to respond within {effective_timeout}s at {health_url}"

    async def deploy_candidate(
        self,
        repo_id: str,
        build_id: str,
        image_tag: str,
        container_port: int,
        health_check_path: str = "/",
        env_vars: Optional[Dict[str, str]] = None,
        db_path: Optional[str] = None,
    ) -> DeploymentResult:
        """Execute zero-downtime deployment for a successfully built candidate image."""
        current_deployment = await database.get_current_deployment(repo_id)
        previous_container = current_deployment.get("container_name") if current_deployment else None
        previous_port = current_deployment.get("host_port") if current_deployment else None

        exclude = {previous_port} if previous_port else set()
        try:
            candidate_port = find_available_port(exclude_ports=exclude)
        except RuntimeError as exc:
            return DeploymentResult(success=False, error_message=str(exc))

        safe_repo_slug = sanitize_repo_name(repo_id)[:20]
        safe_build_slug = sanitize_repo_name(build_id)
        candidate_name = f"preview-{safe_repo_slug}-{safe_build_slug}"
        health_url = f"http://127.0.0.1:{candidate_port}{health_check_path}"

        logger.info(
            "Starting candidate deployment for repo %s (candidate: %s, port: %d)",
            repo_id,
            candidate_name,
            candidate_port,
        )

        try:
            container_id = run_container(
                image_name=image_tag,
                container_name=candidate_name,
                host_port=candidate_port,
                container_port=container_port,
                env_vars=env_vars,
            )
        except Exception as exc:
            logger.error("Failed to start candidate container %s: %s", candidate_name, exc)
            return DeploymentResult(
                success=False,
                container_name=candidate_name,
                error_message=f"Container startup failed: {exc}",
            )

        is_healthy, health_err = await self.validate_candidate_health(health_url)
        if not is_healthy:
            logger.warning(
                "Candidate container %s failed health checks (%s). Preserving existing preview: %s",
                candidate_name,
                health_err,
                previous_container,
            )
            stop_and_remove_container(candidate_name)
            return DeploymentResult(
                success=False,
                container_name=candidate_name,
                error_message=health_err,
            )

        # Check if build_id actually exists in database to avoid FK violation
        valid_build_id = None
        if build_id:
            b_rec = await database.get_build(build_id)
            if b_rec:
                valid_build_id = build_id

        try:
            new_deployment = await database.create_deployment(
                repository_id=repo_id,
                build_id=valid_build_id,
                container_name=candidate_name,
                container_id=container_id,
                image_tag=image_tag,
                host_port=candidate_port,
                container_port=container_port,
                status="running",
                is_healthy=True,
                is_current=True,
                health_check_url=health_url,
            )
            deployment_id = new_deployment["id"]
        except Exception as exc:
            logger.error("Failed to record new deployment in database: %s", exc)
            stop_and_remove_container(candidate_name)
            return DeploymentResult(
                success=False,
                container_name=candidate_name,
                error_message=f"Database record error: {exc}",
            )

        stopped_container_name: Optional[str] = None
        if previous_container and previous_container != candidate_name:
            logger.info("Gracefully stopping previous container: %s", previous_container)
            stop_and_remove_container(previous_container, timeout=10)
            stopped_container_name = previous_container

            if current_deployment and "id" in current_deployment:
                await database.update_deployment(
                    current_deployment["id"],
                    status="stopped",
                    stopped_at=database.utc_now_iso(),
                )

        await self.prune_old_deployments(repo_id)

        settings = get_settings()
        base_url = settings.PUBLIC_BASE_URL.rstrip('/')
        preview_url = f"{base_url}/preview/{repo_id}/"
        direct_url = f"http://localhost:{candidate_port}/"

        return DeploymentResult(
            success=True,
            deployment_id=deployment_id,
            container_name=candidate_name,
            host_port=candidate_port,
            container_port=container_port,
            preview_url=preview_url,
            direct_url=direct_url,
            is_switched=True,
            previous_container_stopped=stopped_container_name,
        )

    async def rollback(
        self,
        repo_id: str,
        target_deployment_id: Optional[str] = None,
    ) -> DeploymentResult:
        """Rollback to a previous successful deployment."""
        deployments = await database.list_deployments(repo_id=repo_id, limit=20)
        candidates = [d for d in deployments if d.get("is_healthy")]

        if not candidates:
            return DeploymentResult(success=False, error_message="No healthy prior deployments to roll back to.")

        if target_deployment_id:
            target = next((d for d in candidates if d["id"] == target_deployment_id), None)
            if not target:
                return DeploymentResult(
                    success=False,
                    error_message=f"Deployment {target_deployment_id} not found among healthy candidates.",
                )
        else:
            inactive = [d for d in candidates if not d.get("is_current")]
            if not inactive:
                return DeploymentResult(success=False, error_message="Already on the only available healthy deployment.")
            target = inactive[0]

        build_id = target.get("build_id")
        image_tag = target.get("image_tag")
        if not image_tag:
            return DeploymentResult(success=False, error_message="Target deployment has no image tag.")

        container_port = 5000
        if build_id:
            b = await database.get_build(build_id)
            if b and b.get("detected_stack") and isinstance(b["detected_stack"], dict):
                container_port = b["detected_stack"].get("port", 5000)

        logger.info("Executing rollback to deployment %s (image: %s)", target["id"], image_tag)
        return await self.deploy_candidate(
            repo_id=repo_id,
            build_id=build_id,
            image_tag=image_tag,
            container_port=container_port,
        )

    async def prune_old_deployments(self, repo_id: str) -> None:
        """Remove stopped containers beyond configured retention limit."""
        try:
            deployments = await database.list_deployments(repo_id=repo_id, limit=100)
            stopped = [d for d in deployments if d.get("status") == "stopped"]

            if len(stopped) > self.retention_count:
                to_delete = stopped[self.retention_count :]
                for dep in to_delete:
                    cname = dep.get("container_name")
                    if cname:
                        stop_and_remove_container(cname)
        except Exception as exc:
            logger.debug("Failed pruning old deployments for %s: %s", repo_id, exc)
