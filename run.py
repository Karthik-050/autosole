"""
Unified Automator & Collaborative Workspace Launcher

Usage:
    python run.py                   # Starts the unified backend + UI on http://127.0.0.1:8000
    python run.py --port 8080       # Custom port
    python run.py --test            # Runs integration test suites
"""

import sys
import argparse
import os
import subprocess
import shutil
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = ROOT_DIR / "collaborative-workspace"

from dotenv import load_dotenv

# The root .env.example documents the settings for this launcher and the
# Collaborative Workspace backend. Keep process-level environment values first.
load_dotenv(ROOT_DIR / ".env", override=False)

# Add collaborative-workspace to sys.path
sys.path.insert(0, str(WORKSPACE_DIR))

def run_tests():
    print("=" * 60)
    print(" Running Backend Integration Tests...")
    print("=" * 60)
    res1 = subprocess.run([sys.executable, "-m", "unittest", "tests/test_backend_integration.py"], cwd=str(WORKSPACE_DIR))
    print("\n" + "=" * 60)
    print(" Running API Endpoints Tests...")
    print("=" * 60)
    res2 = subprocess.run([sys.executable, "-m", "unittest", "tests/test_api_endpoints.py"], cwd=str(WORKSPACE_DIR))
    print("\n" + "=" * 60)
    print(" Running Project Detection Tests...")
    print("=" * 60)
    res3 = subprocess.run([sys.executable, "test_project_detect.py"], cwd=str(WORKSPACE_DIR))

    success = (res1.returncode == 0 and res2.returncode == 0 and res3.returncode == 0)
    if success:
        print("\nAll integration tests PASSED successfully!")
    else:
        print("\nSome tests failed. Please review error tracebacks above.")
        sys.exit(1)

def start_server(host="127.0.0.1", port=8000, reload=True):
    import uvicorn
    automator_dir = ROOT_DIR / "new-automator"
    automator_port = int(os.getenv("AUTOMATOR_PORT", "8001"))
    child_processes = []

    def start_companion(name, command, cwd, env=None):
        try:
            process = subprocess.Popen(command, cwd=str(cwd), env=env)
            child_processes.append((name, process))
            time.sleep(1)
            if process.poll() is not None:
                print(f"{name} exited during startup (code {process.returncode}).")
            else:
                print(f"{name} started (PID {process.pid}).")
        except FileNotFoundError:
            print(f"{name} could not start: executable not found ({command[0]}).")

    automator_env = os.environ.copy()
    automator_env["AUTOMATOR_PORT"] = str(automator_port)
    start_companion(
        "Automator CI/CD API",
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", str(automator_port)],
        automator_dir,
        automator_env,
    )

    ngrok_executable = shutil.which("ngrok")
    if ngrok_executable:
        start_companion("ngrok tunnel", [ngrok_executable, "http", str(automator_port)], ROOT_DIR)
    else:
        print("ngrok was not found; install it and configure an ngrok account to expose port 8001.")

    print("=" * 60)
    print(f" Starting Unified Automator & Collaborative Workspace Server")
    print(f" API & Dashboard: http://{host}:{port}")
    print(f" Automator CI/CD: http://127.0.0.1:{automator_port}")
    print(f" Interactive Docs: http://{host}:{port}/docs")
    print("=" * 60)
    # Workspace contents are user-managed project files. Watching the whole
    # workspace root causes Uvicorn to restart when users create or run files,
    # which can interrupt the in-flight run request. Reload backend source only.
    server_options = {
        "host": host,
        "port": port,
        "reload": reload,
        "app_dir": str(WORKSPACE_DIR),
    }
    if reload:
        server_options["reload_dirs"] = [str(WORKSPACE_DIR / "backend")]
    try:
        uvicorn.run("backend.main:app", **server_options)
    finally:
        for name, process in reversed(child_processes):
            if process.poll() is None:
                print(f"Stopping {name}...")
                process.terminate()
        for _, process in reversed(child_processes):
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.test:
        run_tests()
    else:
        debug_enabled = os.getenv("DEBUG", "true").strip().lower() in ("1", "true", "yes", "on")
        start_server(host=args.host, port=args.port, reload=debug_enabled and not args.no_reload)


def build_parser():
    """Build a parser using explicit CLI options over documented environment defaults."""
    parser = argparse.ArgumentParser(description="Unified Automator & Collaborative Workspace Launcher")
    parser.add_argument("--test", action="store_true", help="Run integration test suite")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"), help="Server host (default: HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")), help="Server port (default: PORT or 8000)")
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload")
    return parser

if __name__ == "__main__":
    main()
