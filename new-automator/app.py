"""Automator CI/CD Application Entry Point.

Provides an upgraded CLI interface supporting Git repository automation,
legacy ZIP project workflows, and the FastAPI Web Dashboard & REST API server.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
from pathlib import Path
import re
import sys
from typing import Optional

from analyzer.detector import detect_project
from config import get_settings
import database
from deployment.diagnostics import format_diagnostics_report, get_preview_diagnostics, is_port_listening
from docker.generator import build_image, generate_dockerfile, run_container, stop_and_remove_container
from git_integration.repository import GitRepository
from git_integration.validators import sanitize_repo_name, validate_branch_name, validate_git_url
from jenkins_automation import client as jenkins_client
from jenkins_automation.job_generator import generate_pipeline
from jenkins_automation.manager import ensure_jenkins_running
from orchestrator import BuildOrchestrator
from project_manager import extract_project
from server import app

logger = logging.getLogger(__name__)
settings = get_settings()

DEFAULT_ZIP_FILE = settings.PROJECTS_DIR / "test-project.zip"
CONTAINER_PORT = settings.DEFAULT_CONTAINER_PORT
HOST_PORT = settings.DEFAULT_HOST_PORT


# ============================================================
# SAFE DEPLOYMENT NAMING
# ============================================================

def create_safe_name(project_name: str) -> str:
    """Convert a project name into a safe Docker naming component."""
    return sanitize_repo_name(project_name)


# ============================================================
# LEGACY ZIP PROJECT SELECTION
# ============================================================

def select_project_zip() -> Path:
    """Ask the user which project ZIP should be deployed (legacy workflow)."""
    print("\n========== PROJECT SELECTION (ZIP) ==========")
    print("Enter the full path to your project ZIP.")
    print("Press Enter to use the default test project.")

    zip_input = input("Project ZIP path: ").strip().strip('"')

    if not zip_input:
        zip_path = DEFAULT_ZIP_FILE
    else:
        zip_path = Path(zip_input).expanduser()
        if not zip_path.is_absolute():
            zip_path = Path.cwd() / zip_path

    zip_path = zip_path.resolve()

    if not zip_path.exists():
        raise FileNotFoundError(f"Project ZIP not found: {zip_path}")
    if not zip_path.is_file():
        raise ValueError(f"The selected path is not a file: {zip_path}")
    if zip_path.suffix.lower() != ".zip":
        raise ValueError("Invalid file type. Please select a .zip file.")

    print(f"\nSelected ZIP: {zip_path}")
    return zip_path


# ============================================================
# WORKFLOW 1: GIT REPOSITORY CI/CD (PRIMARY WORKFLOW)
# ============================================================

async def run_git_workflow(
    repo_url: Optional[str] = None,
    branch_name: Optional[str] = None,
    serve_after: bool = False,
) -> bool:
    """Execute the primary Git repository connection and build workflow."""
    print("\n" + "=" * 60)
    print("       CONNECT & BUILD GIT REPOSITORY (PRIMARY WORKFLOW)")
    print("=" * 60)

    await database.init_db(settings.DB_PATH)

    if not repo_url:
        repo_url = input("\nEnter Git repository HTTPS URL: ").strip()

    if not repo_url:
        print("ERROR: Repository URL is required.")
        return False

    try:
        parsed = validate_git_url(repo_url, allowed_providers=settings.ALLOWED_GIT_PROVIDERS)
    except ValueError as exc:
        print(f"\nURL VALIDATION ERROR: {exc}")
        return False

    if not branch_name:
        branch_input = input("Branch name (press Enter for 'main'): ").strip()
        branch_name = branch_input if branch_input else "main"

    try:
        clean_branch = validate_branch_name(branch_name)
    except ValueError as exc:
        print(f"\nBRANCH VALIDATION ERROR: {exc}")
        return False

    git_repo = GitRepository(settings.REPOS_DIR)
    repo_id = git_repo.generate_repo_id(parsed.clone_url)

    existing = await database.get_repository(repo_id)
    token = None

    if existing:
        repo = existing
        token = repo.get("credential_id")
        print(f"Repository already connected with ID: {repo['id']}")
    else:
        is_private_input = input("Is this a private repository? (y/N): ").strip().lower()
        if is_private_input == "y":
            token = getpass.getpass("Enter Personal Access Token: ").strip()

        print(f"\nValidating repository access to {parsed.clone_url}...")
        is_accessible = git_repo.validate_access(parsed.clone_url, credential_token=token)
        if not is_accessible and token:
            print("ERROR: Inaccessible repository or invalid authentication credentials.")
            return False

        repo = await database.create_repository(
            url=parsed.original_url,
            provider=parsed.provider,
            name=parsed.repo_name,
            owner=parsed.owner,
            default_branch=clean_branch,
            is_private=bool(token),
            credential_id=token,
            repo_id=repo_id,
        )
        print(f"Repository registered with ID: {repo['id']}")

    print("\nQueueing CI/CD build pipeline...")
    build = await database.create_build(
        repository_id=repo["id"],
        commit_sha="HEAD",
        branch=clean_branch,
        trigger_type="cli_manual",
        status="queued",
    )
    build_id = build["id"]
    print(f"Build queued (Build ID: {build_id[:8]}, Number #{build['build_number']})")

    print("\nExecuting pipeline stages...")
    orchestrator = BuildOrchestrator()
    result = await orchestrator.execute_build(
        repository_id=repo["id"],
        build_id=build_id,
        branch=clean_branch,
        trigger_type="cli_manual",
    )

    log_path = settings.LOGS_DIR / f"{build_id}.log"
    print("\n" + "=" * 60)

    if result.get("success"):
        print("             PIPELINE COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        preview_url = result.get("preview_url")
        direct_url = result.get("direct_url")
        host_port = result.get("host_port")

        server_active = is_port_listening(settings.HOST, settings.PORT)

        print("\n[Preview URLs]")
        print(f"  * Gateway Preview URL : {preview_url}")
        print(f"  * Direct Container URL: {direct_url}")

        if server_active:
            print(f"\nGateway server is ACTIVE on port {settings.PORT}.")
            print(f"Open in your browser: {preview_url}")
            print(f"\nDetailed log available at: {log_path}")
            return False
        else:
            print(f"\nNOTE: The Automator Gateway server is NOT currently running on port {settings.PORT}.")
            print(f"      The container is running live in Docker on host port {host_port}.")
            print(f"      -> Direct Access URL : {direct_url}  (Works immediately!)")
            print(f"      -> Gateway URL       : {preview_url}  (Requires Automator server)")

            should_serve = serve_after
            if not should_serve and sys.stdin.isatty():
                try:
                    ans = input("\nWould you like to start the Automator Gateway server now? (Y/n): ").strip().lower()
                    should_serve = ans in ("", "y", "yes")
                except (EOFError, KeyboardInterrupt):
                    should_serve = False

            print(f"\nDetailed log available at: {log_path}")
            return should_serve
    else:
        print("                 PIPELINE BUILD FAILED")
        print("=" * 60)
        print(f"Reason: {result.get('error') or result.get('error_message')}")
        print(f"\nDetailed log available at: {log_path}")
        return False


# ============================================================
# WORKFLOW 2: TRIGGER FOR EXISTING REPO
# ============================================================

async def trigger_existing_repo() -> bool:
    """List connected repositories and trigger a build."""
    await database.init_db(settings.DB_PATH)
    repos = await database.list_repositories()

    if not repos:
        print("\nNo connected repositories found. Please connect a repository first.")
        return False

    print("\nConnected Repositories:")
    for idx, r in enumerate(repos, 1):
        print(f"  {idx}) {r['owner']}/{r['name']} (ID: {r['id']}, Branch: {r['default_branch']})")

    choice = input("\nSelect repository number: ").strip()
    try:
        idx = int(choice) - 1
        if not (0 <= idx < len(repos)):
            print("Invalid selection.")
            return False
        selected = repos[idx]
    except ValueError:
        print("Invalid number.")
        return False

    branch = input(f"Branch [{selected['default_branch']}]: ").strip() or selected["default_branch"]
    return await run_git_workflow(selected["url"], branch)


# ============================================================
# WORKFLOW 3: LEGACY ZIP WORKFLOW (COMPATIBILITY)
# ============================================================

def run_legacy_zip_workflow(provided_zip: Optional[str] = None) -> None:
    """Run the ZIP-based deployment pipeline with real build and health verification."""
    print()
    print("=" * 60)
    print("      AUTOMATOR CI/CD SYSTEM (ZIP WORKFLOW)")
    print("=" * 60)

    print("\nSTEP 1: Selecting project ZIP...\n")
    if provided_zip:
        zip_file = Path(provided_zip).expanduser().resolve()
        if not zip_file.exists():
            raise FileNotFoundError(f"Project ZIP not found: {zip_file}")
    else:
        zip_file = select_project_zip()

    print("\nSTEP 2: Starting Jenkins environment...\n")
    try:
        ensure_jenkins_running()
        jenkins_available = True
        print("Jenkins environment is ready.")
    except Exception as exc:
        jenkins_available = False
        print(f"Jenkins environment offline ({exc}). Will proceed with local Docker engine.")

    print("\nSTEP 3: Extracting project...\n")
    project_path = extract_project(zip_file)
    project_name = project_path.name
    print("Project extracted to:", project_path)
    print("Project name:", project_name)

    print("\nSTEP 4: Detecting project type...\n")
    detection = detect_project(project_path)
    project_type = str(detection)
    print("Detected project type:", project_type)
    print(f"Language: {detection.language}, Manager: {detection.dependency_manager}, Framework: {detection.framework}")

    if project_type == "unknown" and detection.confidence == 0:
        raise RuntimeError("Could not detect project type.")

    print("\nSTEP 5: Generating Dockerfile...\n")
    dockerfile = generate_dockerfile(project_path, detection)
    print("Dockerfile:", dockerfile)

    print("\nSTEP 6: Preparing deployment configuration...\n")
    safe_name = create_safe_name(project_name)
    image_name = f"automator-{safe_name}:latest"
    container_name = f"automator-{safe_name}"

    from deployment.manager import find_available_port
    allocated_host_port = find_available_port(start_port=5100)

    print("Image name     :", image_name)
    print("Container name :", container_name)
    print("Container port :", detection.port)
    print("Host port      :", allocated_host_port)

    # If Jenkins credentials provided, trigger Jenkins; otherwise build locally
    use_jenkins = False
    if jenkins_available and sys.stdin.isatty():
        try:
            ans = input("\nTrigger build via Jenkins? (y/N): ").strip().lower()
            use_jenkins = ans in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            use_jenkins = False

    if use_jenkins:
        print("\nSTEP 7: Generating Jenkins pipeline...\n")
        pipeline_script = generate_pipeline(
            project_name=project_name,
            image_name=image_name,
            container_name=container_name,
            container_port=detection.port,
            detection_result=detection,
            health_check_path=detection.health_check_path,
        )

        print("\nSTEP 8: Connecting to Jenkins...\n")
        username = input("Jenkins username: ").strip()
        api_token = getpass.getpass("Jenkins API token: ").strip()

        server = jenkins_client.connect_to_jenkins(
            settings.JENKINS_URL,
            username,
            api_token,
        )

        if server is None:
            raise RuntimeError("Could not connect to Jenkins.")

        job_name = f"automator-{safe_name}"
        jenkins_client.create_job(server, job_name, pipeline_script)
        queue_id = jenkins_client.trigger_job(server, job_name)
        print("Jenkins job configured and queued:", job_name, f"(Queue ID: {queue_id})")

        print("\nWaiting for Jenkins build to start and complete...")
        build_num = jenkins_client.get_build_from_queue(server, queue_id, timeout=60)
        if build_num:
            build_info = jenkins_client.wait_for_build_completion(server, job_name, build_num, timeout=settings.DOCKER_BUILD_TIMEOUT)
            result_status = (build_info or {}).get("result")
            print(f"Jenkins Build #{build_num} finished with status: {result_status}")
            if result_status != "SUCCESS":
                raise RuntimeError(f"Jenkins build failed with status {result_status}")
    else:
        print("\nSTEP 7-10: Building Docker Image Locally...\n")
        build_image(project_path, image_name)
        print("Docker image built successfully.")

        print("\nSTEP 11-13: Running Container & Health Check...\n")
        stop_and_remove_container(container_name)
        cid = run_container(image_name, container_name, allocated_host_port, detection.port)
        print("Container running with ID:", cid[:12])

    print("\n" + "=" * 60)
    print("              DEPLOYMENT SUCCESSFUL")
    print("=" * 60)
    print("Project Type :", project_type)
    print("Project Name :", project_name)
    print("Dockerfile   :", dockerfile)
    print("Docker Image :", image_name)
    print("Container    :", container_name)
    print("Live URL     :", f"http://localhost:{allocated_host_port}")


# ============================================================
# WORKFLOW 4: PREVIEW DIAGNOSTICS
# ============================================================

async def run_diagnostics_cli(identifier: Optional[str] = None) -> None:
    """Run interactive or targeted preview diagnostics."""
    await database.init_db(settings.DB_PATH)
    if not identifier:
        deployments = await database.list_deployments(limit=10)
        if not deployments:
            print("\nNo deployments found in database.")
            return
        print("\nRecent Deployments:")
        for idx, d in enumerate(deployments, 1):
            is_cur = " [CURRENT]" if d.get("is_current") else ""
            print(f"  {idx}) Repo: {d['repository_id']} | Port: {d.get('host_port')} | Container: {d.get('container_name')}{is_cur}")
        choice = input("\nSelect deployment number or enter repository ID: ").strip()
        try:
            num = int(choice) - 1
            if 0 <= num < len(deployments):
                identifier = deployments[num]["repository_id"]
            else:
                identifier = choice
        except ValueError:
            identifier = choice

    report = await get_preview_diagnostics(identifier)
    print()
    print(format_diagnostics_report(report))


# ============================================================
# WORKFLOW 5: START WEB DASHBOARD & API SERVER
# ============================================================

def start_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Launch the FastAPI server and Web Dashboard using Uvicorn."""
    import uvicorn
    print("\n" + "=" * 60)
    print(f"      STARTING AUTOMATOR WEB DASHBOARD ON http://{host}:{port}")
    print("=" * 60)
    uvicorn.run("server:app", host=host, port=port, reload=False)


# ============================================================
# CLI INTERACTIVE MENU & ARGUMENT PARSER
# ============================================================

def main() -> None:
    """Application CLI entry point with interactive menu and flag parsing."""
    parser = argparse.ArgumentParser(description="Automator Git & ZIP CI/CD Platform")
    parser.add_argument("--server", action="store_true", help="Start the Web Dashboard & API server")
    parser.add_argument("--jenkins", action="store_true", help="Start the Jenkins controller and Docker daemon containers")
    parser.add_argument("--repo", type=str, help="Git repository HTTPS URL to connect and build")
    parser.add_argument("--branch", type=str, default="main", help="Git branch to build")
    parser.add_argument("--serve", action="store_true", help="Keep the Automator server running after pipeline execution")
    parser.add_argument("--diagnostics", nargs="?", const="", type=str, help="Run preview diagnostics for a repository or deployment ID")
    parser.add_argument("--zip", type=str, help="Path to project ZIP file (ZIP workflow mode)")
    parser.add_argument("--host", type=str, default=settings.HOST, help="Server host binding")
    parser.add_argument("--port", type=int, default=settings.PORT, help="Server port binding")
    args = parser.parse_args()

    if args.server:
        start_server(host=args.host, port=args.port)
        return

    if args.jenkins:
        print("\n" + "=" * 60)
        print("         STARTING JENKINS ENVIRONMENT (CONTROLLER + DIND)")
        print("=" * 60)
        ensure_jenkins_running()
        print("\nJenkins controller is ready at http://localhost:8080")
        return

    if args.diagnostics is not None:
        asyncio.run(run_diagnostics_cli(args.diagnostics if args.diagnostics else None))
        return

    if args.repo:
        should_serve = asyncio.run(run_git_workflow(args.repo, args.branch, serve_after=args.serve))
        if should_serve:
            start_server(host=args.host, port=args.port)
        return

    if args.zip:
        run_legacy_zip_workflow(provided_zip=args.zip)
        return

    # Interactive Menu
    print()
    print("=" * 60)
    print("                  AUTOMATOR CI/CD SYSTEM")
    print("=" * 60)
    print("Select an option:")
    print("  1) Connect Git Repository & Run CI/CD Pipeline (Primary)")
    print("  2) Trigger Pipeline for Existing Connected Repository")
    print("  3) View Preview Diagnostics & Container Status")
    print("  4) Deploy Local Project ZIP (Legacy Compatibility)")
    print("  5) Start Jenkins CI/CD Controller Environment")
    print("  6) Start Automator Web Dashboard & REST API Server")
    print("  7) Exit")

    choice = input("\nEnter choice [1-7]: ").strip()

    if choice == "1":
        should_serve = asyncio.run(run_git_workflow())
        if should_serve:
            start_server(host=args.host, port=args.port)
    elif choice == "2":
        should_serve = asyncio.run(trigger_existing_repo())
        if should_serve:
            start_server(host=args.host, port=args.port)
    elif choice == "3":
        asyncio.run(run_diagnostics_cli())
    elif choice == "4":
        run_legacy_zip_workflow()
    elif choice == "5":
        ensure_jenkins_running()
        print("\nJenkins is ready at http://localhost:8080")
    elif choice == "6":
        start_server(host=args.host, port=args.port)
    elif choice == "7":
        print("Goodbye.")
    else:
        print("Invalid choice.")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"\nAUTOMATION ERROR: {error}")
    except KeyboardInterrupt:
        print("\nAutomation interrupted by user.")
