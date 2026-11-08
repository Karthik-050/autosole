"""Jenkins container and Docker environment management.

Handles Jenkins controller and DinD (Docker-in-Docker) container lifecycles,
networks, and persistent workspace mounts with configurable retries and diagnostics.
"""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import time
from typing import Optional

from config import get_settings

logger = logging.getLogger(__name__)


def run_docker(args: list[str], check: bool = True) -> str:
    """Run a Docker command safely using argument arrays."""
    result = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
    )

    if check and result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Docker command failed: {error if error else 'Unknown Docker error'}")

    return result.stdout.strip()


def is_docker_daemon_available() -> bool:
    """Check if the local Docker daemon is responsive."""
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=10)
        return res.returncode == 0
    except Exception as exc:
        logger.debug("Docker daemon check failed: %s", exc)
        return False


def container_exists(name: str) -> bool:
    """Check whether a Docker container exists."""
    result = subprocess.run(
        ["docker", "inspect", name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def container_running(name: str) -> bool:
    """Check whether a Docker container is running."""
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            "{{.State.Running}}",
            name,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def ensure_network(network_name: Optional[str] = None) -> None:
    """Create Jenkins Docker network if it does not exist."""
    settings = get_settings()
    net = network_name or settings.JENKINS_NETWORK

    result = subprocess.run(
        [
            "docker",
            "network",
            "inspect",
            net,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.info("Creating Jenkins network '%s'...", net)
        run_docker(["network", "create", net])
    else:
        logger.info("Jenkins network '%s' already exists.", net)


def ensure_jenkins_docker() -> None:
    """Start or create Jenkins Docker-in-Docker container."""
    settings = get_settings()
    dind_container = settings.JENKINS_DOCKER_CONTAINER

    if container_exists(dind_container):
        if container_running(dind_container):
            logger.info("Jenkins Docker daemon container '%s' is already running.", dind_container)
        else:
            logger.info("Starting Jenkins Docker daemon container '%s'...", dind_container)
            run_docker(["start", dind_container])
        return

    logger.info("Creating Jenkins Docker container '%s'...", dind_container)
    run_docker([
        "run",
        "-d",
        "--name", dind_container,
        "--network", settings.JENKINS_NETWORK,
        "--network-alias", "docker",
        "--privileged",
        "-p", "5001:5001",
        "-e", "DOCKER_TLS_CERTDIR=/certs",
        "-v", "jenkins-docker-certs-ca:/certs/ca",
        "-v", "jenkins-docker-certs-client:/certs/client",
        "-v", "jenkins-docker-data:/var/lib/docker",
        "docker:dind",
        "--storage-driver", "overlay2",
    ])


def wait_for_docker_daemon(
    max_attempts: Optional[int] = None,
    interval_seconds: Optional[int] = None,
) -> None:
    """Wait until the Jenkins Docker daemon is ready with configurable retries."""
    settings = get_settings()
    attempts = max_attempts if max_attempts is not None else settings.JENKINS_RETRY_ATTEMPTS
    interval = interval_seconds if interval_seconds is not None else settings.JENKINS_RETRY_INTERVAL
    dind_container = settings.JENKINS_DOCKER_CONTAINER

    logger.info("Waiting for Jenkins Docker daemon in '%s' (max %d attempts, %ds interval)...",
                dind_container, attempts, interval)

    last_error = ""
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            [
                "docker",
                "exec",
                dind_container,
                "docker",
                "info",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            logger.info("Jenkins Docker daemon is ready (attempt %d/%d).", attempt, attempts)
            return

        last_error = result.stderr.strip() or result.stdout.strip()
        time.sleep(interval)

    raise RuntimeError(
        f"Jenkins Docker daemon did not become ready after {attempts * interval}s. "
        f"Container: {dind_container}. Last error: {last_error}"
    )


def ensure_jenkins() -> None:
    """Start or create Jenkins controller container."""
    settings = get_settings()
    jenkins_container = settings.JENKINS_CONTAINER
    projects_dir = str(settings.PROJECTS_DIR.resolve())
    repos_dir = str(settings.REPOS_DIR.resolve())

    if container_exists(jenkins_container):
        if container_running(jenkins_container):
            logger.info("Jenkins controller '%s' is already running.", jenkins_container)
        else:
            logger.info("Starting Jenkins controller '%s'...", jenkins_container)
            run_docker(["start", jenkins_container])
        return

    logger.info("Creating Jenkins container '%s' with workspace mounts...", jenkins_container)
    run_docker([
        "run",
        "-d",
        "--name", jenkins_container,
        "--network", settings.JENKINS_NETWORK,
        "--network-alias", "jenkins",
        "-p", "8080:8080",
        "-p", "50000:50000",
        "-v", "jenkins_home:/var/jenkins_home",
        "-v", "jenkins-docker-certs-client:/certs/client:ro",
        "-v", f"{projects_dir}:/workspace/projects",
        "-v", f"{repos_dir}:/workspace/repos",
        "-e", "DOCKER_HOST=tcp://docker:2376",
        "-e", "DOCKER_CERT_PATH=/certs/client",
        "-e", "DOCKER_TLS_VERIFY=1",
        "automator-jenkins",
    ])


def ensure_jenkins_running() -> None:
    """Complete Jenkins environment startup orchestration."""
    if not is_docker_daemon_available():
        raise RuntimeError("Docker daemon is not running or responsive. Please start Docker Desktop first.")

    ensure_network()
    ensure_jenkins_docker()
    wait_for_docker_daemon()
    ensure_jenkins()
