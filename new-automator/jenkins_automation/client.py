"""Automator Jenkins Client and API Integration Module.

Provides robust Jenkins connectivity, job configuration, build triggering,
real-time status polling, and console log retrieval with error resilience.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import jenkins

logger = logging.getLogger(__name__)


# ============================================================
# CONNECT TO JENKINS
# ============================================================

def connect_to_jenkins(
    jenkins_url: str,
    username: str,
    api_token: str,
    timeout: int = 30,
) -> Optional[jenkins.Jenkins]:
    """Establish and test connection to Jenkins controller.

    Args:
        jenkins_url: Base URL of the Jenkins server.
        username: Jenkins user account.
        api_token: User API token or password.
        timeout: Network timeout in seconds.

    Returns:
        jenkins.Jenkins instance or None if connection fails.
    """
    logger.info("Connecting to Jenkins at %s", jenkins_url)

    try:
        server = jenkins.Jenkins(
            jenkins_url,
            username=username,
            password=api_token,
            timeout=timeout,
        )

        user = server.get_whoami()
        version = server.get_version()

        logger.info(
            "Connected to Jenkins successfully! User: %s, Version: %s",
            user.get("fullName", username),
            version,
        )
        return server

    except Exception as exc:
        logger.warning("Jenkins connection failed: %s", exc)
        return None


# ============================================================
# HEALTH & READINESS CHECK
# ============================================================

def check_jenkins_healthy(server: jenkins.Jenkins) -> bool:
    """Verify that Jenkins is responsive and reachable."""
    try:
        server.get_version()
        return True
    except Exception as exc:
        logger.debug("Jenkins health check failed: %s", exc)
        return False


# ============================================================
# CREATE OR UPDATE JENKINS JOB
# ============================================================

def create_job(
    server: jenkins.Jenkins,
    job_name: str,
    pipeline_script: str,
) -> None:
    """Create a pipeline job or update it if it already exists."""
    job_config = f"""<flow-definition plugin="workflow-job">
    <description>Automator generated pipeline</description>
    <keepDependencies>false</keepDependencies>
    <properties/>
    <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition" plugin="workflow-cps">
        <script><![CDATA[
{pipeline_script}
        ]]></script>
        <sandbox>true</sandbox>
    </definition>
    <triggers/>
    <disabled>false</disabled>
</flow-definition>
"""

    if not server.job_exists(job_name):
        logger.info("Creating Jenkins job: %s", job_name)
        server.create_job(job_name, job_config)
    else:
        logger.info("Updating existing Jenkins job: %s", job_name)
        server.reconfig_job(job_name, job_config)


# ============================================================
# TRIGGER JENKINS JOB
# ============================================================

def trigger_job(
    server: jenkins.Jenkins,
    job_name: str,
    parameters: Optional[Dict[str, Any]] = None,
) -> int:
    """Trigger a build of the specified job.

    Returns:
        int: Queue item ID.
    """
    logger.info("Triggering Jenkins job %s (params: %s)", job_name, parameters)
    try:
        if parameters:
            queue_id = server.build_job(job_name, parameters=parameters)
        else:
            queue_id = server.build_job(job_name)

        logger.info("Jenkins build queued with ID %s", queue_id)
        return queue_id

    except Exception as exc:
        logger.error("Failed to trigger Jenkins job %s: %s", job_name, exc)
        raise


# ============================================================
# QUEUE TO BUILD NUMBER RESOLUTION
# ============================================================

def get_build_from_queue(
    server: jenkins.Jenkins,
    queue_id: int,
    timeout: int = 60,
    poll_interval: int = 2,
) -> Optional[int]:
    """Poll Jenkins queue until a build number is assigned to the queue item."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            item = server.get_queue_item(queue_id)
            if not item:
                time.sleep(poll_interval)
                continue

            executable = item.get("executable")
            if executable and "number" in executable:
                return executable["number"]

            if item.get("cancelled", False):
                logger.warning("Queue item %s was cancelled", queue_id)
                return None

        except Exception as exc:
            logger.debug("Error checking queue item %s: %s", queue_id, exc)

        time.sleep(poll_interval)

    logger.warning("Timed out waiting for queue item %s to start building", queue_id)
    return None


# ============================================================
# GET BUILD STATUS & CONSOLE OUTPUT
# ============================================================

def get_latest_build(
    server: jenkins.Jenkins,
    job_name: str,
) -> Optional[Dict[str, Any]]:
    """Retrieve details for the latest build of a job."""
    try:
        job_info = server.get_job_info(job_name)
        last_build = job_info.get("lastBuild")
        if not last_build:
            return None

        build_number = last_build["number"]
        return server.get_build_info(job_name, build_number)

    except Exception as exc:
        logger.warning("Could not get build information for %s: %s", job_name, exc)
        return None


def get_build_info(
    server: jenkins.Jenkins,
    job_name: str,
    build_number: int,
) -> Optional[Dict[str, Any]]:
    """Get status and metadata for a specific build number."""
    try:
        return server.get_build_info(job_name, build_number)
    except Exception as exc:
        logger.warning("Failed to get build info for %s #%d: %s", job_name, build_number, exc)
        return None


def get_build_console_output(
    server: jenkins.Jenkins,
    job_name: str,
    build_number: int,
) -> str:
    """Fetch raw console logs for a build."""
    try:
        return server.get_build_console_output(job_name, build_number)
    except Exception as exc:
        logger.warning("Failed to fetch console output for %s #%d: %s", job_name, build_number, exc)
        return f"Could not retrieve console output: {exc}"


def wait_for_build_completion(
    server: jenkins.Jenkins,
    job_name: str,
    build_number: int,
    timeout: int = 300,
    poll_interval: int = 3,
) -> Optional[Dict[str, Any]]:
    """Poll until the specified build completes or times out."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        build_info = get_build_info(server, job_name, build_number)
        if build_info and not build_info.get("building", True):
            return build_info

        time.sleep(poll_interval)

    logger.warning("Timed out waiting for %s #%d to complete", job_name, build_number)
    return get_build_info(server, job_name, build_number)
