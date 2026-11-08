"""Automator Jenkins CI/CD Automation Package."""

from .client import (
    check_jenkins_healthy,
    connect_to_jenkins,
    create_job,
    get_build_console_output,
    get_build_from_queue,
    get_build_info,
    get_latest_build,
    trigger_job,
    wait_for_build_completion,
)
from .job_generator import generate_pipeline, sanitize_name
from .manager import (
    container_exists,
    container_running,
    ensure_jenkins,
    ensure_jenkins_docker,
    ensure_jenkins_running,
    ensure_network,
    is_docker_daemon_available,
    run_docker,
    wait_for_docker_daemon,
)

__all__ = [
    "check_jenkins_healthy",
    "connect_to_jenkins",
    "container_exists",
    "container_running",
    "create_job",
    "ensure_jenkins",
    "ensure_jenkins_docker",
    "ensure_jenkins_running",
    "ensure_network",
    "generate_pipeline",
    "get_build_console_output",
    "get_build_from_queue",
    "get_build_info",
    "get_latest_build",
    "is_docker_daemon_available",
    "run_docker",
    "sanitize_name",
    "trigger_job",
    "wait_for_build_completion",
    "wait_for_docker_daemon",
]
