"""Automator Zero-Downtime Preview Reverse Proxy.

Routes incoming HTTP requests destined for `/preview/{repo_id}/*` to the active
healthy container's host port with zero downtime, supporting trailing slash
redirection, Location header rewriting, HTML base tag injection, and multi-target fallback.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import httpx

import database

logger = logging.getLogger(__name__)

# Exclude hop-by-hop headers from proxying
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


def rewrite_redirect_location(location: str, preview_prefix: str, candidate_hosts: List[str]) -> str:
    """Rewrite upstream Location redirect header so it remains inside the preview subpath.

    Args:
        location: Original Location header from upstream.
        preview_prefix: Gateway prefix, e.g. '/preview/my-repo'.
        candidate_hosts: List of upstream base URLs to strip if present.

    Returns:
        Rewritten Location URL.
    """
    clean_prefix = preview_prefix.rstrip("/")

    # Check for upstream absolute URLs
    for host in candidate_hosts:
        if location.startswith(host):
            subpath = location[len(host) :]
            if not subpath.startswith("/"):
                subpath = "/" + subpath
            return f"{clean_prefix}{subpath}"

    # Check for root-relative paths like '/login' or '/dashboard'
    if location.startswith("/"):
        if not location.startswith(clean_prefix):
            return f"{clean_prefix}{location}"
        return location

    return location


def inject_base_href(html_content: str, base_href: str) -> str:
    """Inject <base href="..."> into HTML content if not already present.

    Args:
        html_content: HTML document string.
        base_href: Target base URL prefix ending in '/'.

    Returns:
        HTML document with <base> tag injected.
    """
    if "<base " in html_content.lower():
        return html_content

    # Inject right after <head> or <HEAD> tag
    head_match = re.search(r"<head\b[^>]*>", html_content, re.IGNORECASE)
    if head_match:
        end_pos = head_match.end()
        base_tag = f'\n    <base href="{base_href}">'
        return html_content[:end_pos] + base_tag + html_content[end_pos:]

    return html_content


async def proxy_preview_request(repo_id: str, path: str, request: Request) -> Response:
    """Forward request to currently active deployment container for repository.

    Args:
        repo_id: Repository identifier, repo name, or deployment identifier.
        path: Sub-path to forward to the target container.
        request: Incoming FastAPI Request.

    Returns:
        FastAPI Response proxying the upstream container response.
    """
    # Enforce trailing slash on the preview root to ensure relative asset URLs resolve correctly
    req_path = request.url.path
    if (not path or path == "") and not req_path.endswith("/"):
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(url=f"{req_path}/{query}", status_code=307)

    deployment = await database.find_active_deployment(repo_id)

    if not deployment or not deployment.get("host_port") or not deployment.get("is_healthy"):
        return HTMLResponse(
            status_code=503,
            content=f"""<!DOCTYPE html>
<html>
<head>
    <title>Preview Unavailable - Automator</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
        .card {{ background: #1e293b; padding: 2.5rem; border-radius: 12px; max-width: 520px; text-align: center; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #334155; }}
        h1 {{ color: #38bdf8; font-size: 1.5rem; margin-bottom: 0.5rem; }}
        p {{ color: #94a3b8; font-size: 0.95rem; line-height: 1.5; }}
        code {{ background: #0f172a; padding: 0.2rem 0.4rem; border-radius: 4px; color: #38bdf8; }}
        .spinner {{ border: 3px solid #334155; border-top: 3px solid #38bdf8; border-radius: 50%; width: 36px; height: 36px; animation: spin 1s linear infinite; margin: 1.5rem auto; }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
    </style>
</head>
<body>
    <div class="card">
        <div class="spinner"></div>
        <h1>Deployment Candidate Starting</h1>
        <p>No active healthy preview container found for repository <code>{repo_id}</code>.</p>
        <p>A pipeline build may be in progress or healthy checks are initializing. This page will automatically refresh every 5 seconds.</p>
    </div>
</body>
</html>""",
        )

    host_port = deployment["host_port"]
    container_port = deployment.get("container_port", 5000)
    container_name = deployment.get("container_name", "")
    direct_container_url = f"http://localhost:{host_port}/"

    # Upstream candidates in priority order:
    # 1. 127.0.0.1 on Windows/Linux host
    # 2. host.docker.internal when Automator itself runs inside a Docker container
    # 3. Direct container DNS name on Docker bridge networks
    clean_subpath = path.lstrip("/")
    candidate_bases = [
        f"http://127.0.0.1:{host_port}",
        f"http://host.docker.internal:{host_port}",
    ]
    if container_name:
        candidate_bases.append(f"http://{container_name}:{container_port}")

    # Filter incoming request headers
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
    }
    client_host = request.client.host if request.client else "127.0.0.1"
    headers["Host"] = f"127.0.0.1:{host_port}"
    headers["X-Forwarded-For"] = client_host
    headers["X-Forwarded-Proto"] = request.url.scheme
    headers["X-Forwarded-Host"] = request.headers.get("host", "localhost:8000")
    headers["X-Forwarded-Prefix"] = f"/preview/{repo_id}"

    body = await request.body()
    query_str = f"?{request.url.query}" if request.url.query else ""

    last_error: Optional[Exception] = None
    upstream_resp = None

    for base_url in candidate_bases:
        target_url = f"{base_url}/{clean_subpath}{query_str}"
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                upstream_resp = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body if body else None,
                )
                if upstream_resp is not None:
                    break
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            last_error = exc
            logger.debug("Candidate target %s unreachable: %s", target_url, exc)
            continue
        except Exception as exc:
            last_error = exc
            logger.error("Error proxying preview request to %s: %s", target_url, exc)
            break

    if upstream_resp is None:
        logger.warning(
            "Connection failed to preview container %s on port %d: %s",
            container_name,
            host_port,
            last_error,
        )
        # Check if caller accepts JSON
        accept_header = request.headers.get("accept", "")
        if "application/json" in accept_header and "text/html" not in accept_header:
            return JSONResponse(
                status_code=502,
                content={
                    "error": "Preview container connection failed",
                    "repository_id": repo_id,
                    "container_name": container_name,
                    "host_port": host_port,
                    "direct_url": direct_container_url,
                    "detail": str(last_error),
                },
            )

        return HTMLResponse(
            status_code=502,
            content=f"""<!DOCTYPE html>
<html>
<head>
    <title>Preview Gateway Error (502) - Automator</title>
    <style>
        body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
        .card {{ background: #1e293b; padding: 2.5rem; border-radius: 12px; max-width: 580px; text-align: left; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #ef4444; }}
        h1 {{ color: #ef4444; font-size: 1.5rem; margin-top: 0; }}
        p {{ color: #cbd5e1; font-size: 0.95rem; line-height: 1.6; }}
        code {{ background: #0f172a; padding: 0.2rem 0.4rem; border-radius: 4px; color: #38bdf8; font-size: 0.9em; }}
        .btn {{ display: inline-block; background: #0284c7; color: #fff; padding: 0.6rem 1.2rem; border-radius: 6px; text-decoration: none; font-weight: 500; margin-top: 1rem; }}
        .btn:hover {{ background: #0369a1; }}
        ul {{ color: #94a3b8; font-size: 0.9rem; padding-left: 1.2rem; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>502 Bad Gateway - Preview Unreachable</h1>
        <p>The Automator gateway was unable to establish a connection with the running preview container.</p>
        <ul>
            <li><strong>Repository ID:</strong> <code>{repo_id}</code></li>
            <li><strong>Container Name:</strong> <code>{container_name}</code></li>
            <li><strong>Host Port Mapping:</strong> <code>{host_port} &rarr; {container_port}</code></li>
        </ul>
        <p>You can access the container directly on its published host port:</p>
        <a class="btn" href="{direct_container_url}" target="_blank">Open Direct Container URL ({direct_container_url})</a>
    </div>
</body>
</html>""",
        )

    # Filter response headers
    resp_headers = {
        key: value
        for key, value in upstream_resp.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }

    # Rewrite Location redirect header if present
    preview_prefix = f"/preview/{repo_id}"
    if "location" in resp_headers:
        resp_headers["location"] = rewrite_redirect_location(
            resp_headers["location"],
            preview_prefix=preview_prefix,
            candidate_hosts=candidate_bases,
        )

    content = upstream_resp.content
    content_type = upstream_resp.headers.get("content-type", "")

    # Inject <base href="..."> into HTML responses if needed
    if "text/html" in content_type.lower() and content:
        try:
            encoding = upstream_resp.encoding or "utf-8"
            html_text = content.decode(encoding, errors="replace")
            base_href = f"{preview_prefix}/"
            modified_html = inject_base_href(html_text, base_href)
            content = modified_html.encode(encoding)
            resp_headers["content-length"] = str(len(content))
        except Exception as exc:
            logger.debug("Failed injecting base href into HTML response: %s", exc)

    return Response(
        content=content,
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=content_type or None,
    )
