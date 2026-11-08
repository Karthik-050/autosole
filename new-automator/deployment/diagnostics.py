"""Automator Preview Diagnostics Engine.

Provides comprehensive diagnostic checks for preview deployments, inspecting
backend server listening status, Docker container state, port bindings,
upstream reachability, and generated URLs with actionable troubleshooting hints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional

import httpx

from config import get_settings
import database

logger = logging.getLogger(__name__)


def is_port_listening(host: str, port: int, timeout: float = 0.8) -> bool:
    """Check if a TCP port is currently accepting connections."""
    target_host = "127.0.0.1" if host in {"0.0.0.0", ""} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((target_host, port))
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False


def inspect_docker_container(container_name: str) -> Dict[str, Any]:
    """Inspect Docker container state using 'docker inspect'."""
    if not container_name:
        return {"status": "none", "exists": False}

    try:
        res = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode != 0:
            return {"status": "not_found", "exists": False, "error": res.stderr.strip()}

        data = json.loads(res.stdout)
        if not data or not isinstance(data, list):
            return {"status": "not_found", "exists": False}

        c_info = data[0]
        state = c_info.get("State", {})
        health = state.get("Health", {})
        net_settings = c_info.get("NetworkSettings", {})
        ports = net_settings.get("Ports", {})
        networks = list(net_settings.get("Networks", {}).keys())

        return {
            "exists": True,
            "status": state.get("Status", "unknown"),
            "running": state.get("Running", False),
            "health": health.get("Status", "no_healthcheck"),
            "exit_code": state.get("ExitCode", 0),
            "started_at": state.get("StartedAt"),
            "networks": networks,
            "ports": ports,
            "image": c_info.get("Config", {}).get("Image"),
        }
    except Exception as exc:
        return {"status": "error", "exists": False, "error": str(exc)}


async def test_direct_connectivity(host_port: int, timeout: float = 3.0) -> Dict[str, Any]:
    """Directly probe the container's published host port with HTTP GET."""
    url = f"http://127.0.0.1:{host_port}/"
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            elapsed_ms = (time.time() - start) * 1000.0
            return {
                "reachable": True,
                "status_code": resp.status_code,
                "response_time_ms": round(elapsed_ms, 2),
                "server_header": resp.headers.get("server"),
                "content_type": resp.headers.get("content-type"),
            }
    except httpx.ConnectError:
        return {"reachable": False, "error": "Connection refused"}
    except httpx.TimeoutException:
        return {"reachable": False, "error": f"Connection timed out after {timeout}s"}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


async def get_preview_diagnostics(preview_id: str) -> Dict[str, Any]:
    """Collect full diagnostic information for a preview deployment.

    Args:
        preview_id: Repository ID, repo name, or deployment ID.

    Returns:
        Structured diagnostic report dictionary.
    """
    settings = get_settings()
    clean_id = preview_id.strip()

    # 1. Check Automator Gateway Server listening status
    server_listening = is_port_listening(settings.HOST, settings.PORT)
    gateway_info = {
        "bind_host": settings.HOST,
        "bind_port": settings.PORT,
        "public_base_url": settings.PUBLIC_BASE_URL,
        "server_listening": server_listening,
    }

    # 2. Database lookup
    deployment = await database.find_active_deployment(clean_id)
    repo = None
    if deployment:
        repo = await database.get_repository(deployment["repository_id"])
    else:
        # Check if repository exists even if no active deployment
        repo = await database.get_repository(clean_id)
        if not repo:
            repo = await database.get_repository_by_url(clean_id)

    repo_id = repo["id"] if repo else (deployment["repository_id"] if deployment else clean_id)
    repo_name = repo["name"] if repo else None

    # Construct URLs
    base_url = settings.PUBLIC_BASE_URL.rstrip("/")
    gateway_preview_url = f"{base_url}/preview/{repo_id}/"

    if not deployment:
        recommendations = [
            f"No active deployment found for identifier '{clean_id}'.",
            "Trigger a new build using: python automator/app.py --repo <git_url>",
        ]
        return {
            "status": "not_found",
            "preview_id": clean_id,
            "repository": {"id": repo_id, "name": repo_name},
            "deployment": None,
            "gateway": gateway_info,
            "preview_url": gateway_preview_url,
            "direct_url": None,
            "recommendations": recommendations,
        }

    host_port = deployment.get("host_port")
    container_port = deployment.get("container_port", 5000)
    container_name = deployment.get("container_name", "")
    direct_container_url = f"http://localhost:{host_port}/" if host_port else None

    # 3. Docker Container State
    docker_info = inspect_docker_container(container_name)

    # 4. Direct HTTP probe
    direct_probe = {"reachable": False, "error": "No host port"}
    if host_port:
        direct_probe = await test_direct_connectivity(host_port)

    # 5. Formulate recommendations and overall health
    recommendations: List[str] = []
    overall_status = "healthy"

    if not docker_info.get("running"):
        overall_status = "offline"
        recommendations.append(
            f"Docker container '{container_name}' is not running (status: {docker_info.get('status')})."
        )
        recommendations.append(f"Check logs with: docker logs {container_name}")
    elif not direct_probe.get("reachable"):
        overall_status = "degraded"
        recommendations.append(
            f"Docker container is running but port {host_port} is not responding ({direct_probe.get('error')})."
        )
        recommendations.append(f"Inspect container logs: docker logs {container_name}")
    elif not server_listening:
        overall_status = "gateway_offline"
        recommendations.append(
            f"The container is healthy on port {host_port}, but the Automator Gateway server on port {settings.PORT} is NOT running."
        )
        recommendations.append(
            f"Access the container immediately at Direct URL: {direct_container_url}"
        )
        recommendations.append(
            f"Start the gateway server with: python automator/app.py --server"
        )
    else:
        recommendations.append(
            f"Everything is operational! Access via Gateway URL: {gateway_preview_url}"
        )
        recommendations.append(
            f"Or access directly via Container URL: {direct_container_url}"
        )

    return {
        "status": overall_status,
        "preview_id": clean_id,
        "repository": {
            "id": repo_id,
            "name": repo_name,
            "owner": repo.get("owner") if repo else None,
        },
        "deployment": {
            "id": deployment.get("id"),
            "container_name": container_name,
            "container_id": deployment.get("container_id"),
            "image_tag": deployment.get("image_tag"),
            "host_port": host_port,
            "container_port": container_port,
            "is_current": deployment.get("is_current"),
            "is_healthy": deployment.get("is_healthy"),
            "health_check_url": deployment.get("health_check_url"),
        },
        "docker": docker_info,
        "direct_probe": direct_probe,
        "gateway": gateway_info,
        "gateway_preview_url": gateway_preview_url,
        "direct_container_url": direct_container_url,
        "recommendations": recommendations,
    }


def format_diagnostics_report(diag: Dict[str, Any]) -> str:
    """Format diagnostic data into an easy-to-read ASCII terminal report."""
    lines: List[str] = [
        "=" * 65,
        "                 AUTOMATOR PREVIEW DIAGNOSTICS",
        "=" * 65,
    ]

    status_str = diag.get("status", "unknown").upper()
    lines.append(f"Overall Status: {status_str}")
    lines.append("-" * 65)

    # Repository
    repo = diag.get("repository") or {}
    lines.append(f"Repository ID : {repo.get('id', 'N/A')}")
    if repo.get("name"):
        lines.append(f"Repository    : {repo.get('owner') or ''}/{repo.get('name')}")

    # Gateway Server
    gw = diag.get("gateway") or {}
    gw_status = "LISTENING (Active)" if gw.get("server_listening") else "STOPPED / NOT LISTENING"
    lines.append(f"\n[Gateway Server]")
    lines.append(f"  Public Base URL   : {gw.get('public_base_url')}")
    lines.append(f"  Bind Address      : {gw.get('bind_host')}:{gw.get('bind_port')}")
    lines.append(f"  Listening Status  : {gw_status}")

    # Deployment
    dep = diag.get("deployment")
    if dep:
        lines.append(f"\n[Preview Container Deployment]")
        lines.append(f"  Container Name    : {dep.get('container_name')}")
        lines.append(f"  Image Tag         : {dep.get('image_tag')}")
        lines.append(f"  Port Mapping      : Host {dep.get('host_port')} -> Container {dep.get('container_port')}")
        lines.append(f"  Database Health   : {'Healthy' if dep.get('is_healthy') else 'Unhealthy'}")
        lines.append(f"  Active Status     : {'Current Active' if dep.get('is_current') else 'Inactive'}")

        # Docker State
        dock = diag.get("docker") or {}
        dock_health = dock.get("health", "no check")
        lines.append(f"\n[Docker Engine Inspection]")
        lines.append(f"  Container Status  : {dock.get('status', 'unknown')}")
        lines.append(f"  Docker Health     : {dock_health}")
        lines.append(f"  Networks          : {', '.join(dock.get('networks', []))}")

        # Direct Probe
        probe = diag.get("direct_probe") or {}
        if probe.get("reachable"):
            lines.append(f"\n[Direct HTTP Probe: 127.0.0.1:{dep.get('host_port')}]")
            lines.append(f"  Connectivity      : REACHABLE (HTTP {probe.get('status_code')})")
            lines.append(f"  Response Time     : {probe.get('response_time_ms')} ms")
        else:
            lines.append(f"\n[Direct HTTP Probe: 127.0.0.1:{dep.get('host_port')}]")
            lines.append(f"  Connectivity      : UNREACHABLE ({probe.get('error')})")

        # Access URLs
        lines.append(f"\n[Access URLs]")
        lines.append(f"  Gateway Preview URL : {diag.get('gateway_preview_url')}")
        lines.append(f"  Direct Container URL: {diag.get('direct_container_url')}")
    else:
        lines.append("\nNo active deployment record found.")

    # Recommendations
    recs = diag.get("recommendations", [])
    if recs:
        lines.append(f"\n[Recommendations & Action Items]")
        for r in recs:
            lines.append(f"  * {r}")

    lines.append("=" * 65)
    return "\n".join(lines)
