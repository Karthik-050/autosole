import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "workspace"

SANDBOX_IMAGE = "python:3.10-slim"


class SandboxRunner:

    def run(self, workspace_id, filename):

        # -----------------------------
        # 1. Validate workspace
        # -----------------------------
        ws_path = (BASE_DIR / workspace_id).resolve()

        if not ws_path.is_dir():
            raise Exception("Workspace not found")

        # -----------------------------
        # 2. Validate filename
        # -----------------------------
        file_path = (ws_path / filename).resolve()

        # Prevent accessing files outside workspace
        if ws_path not in file_path.parents:
            raise Exception("Invalid file path")

        if not file_path.is_file():
            raise Exception("File not found")

        if file_path.suffix.lower() != ".py":
            raise Exception("Unsupported file type")

        # Filename relative to workspace
        relative_file = file_path.relative_to(ws_path)

        # Docker path uses forward slashes
        docker_file = "/app/" + relative_file.as_posix()

        # Windows host path
        host_workspace = str(ws_path)

        # -----------------------------
        # 3. Docker command
        # -----------------------------
        command = [
            "docker",
            "run",
            "--rm",

            # Workspace → container
            "-v",
            f"{host_workspace}:/app",

            # Container working directory
            "-w",
            "/app",

            # Docker image
            SANDBOX_IMAGE,

            # Execute Python
            "python",
            docker_file,
        ]

        print("\n========== SANDBOX ==========")
        print("Workspace:", ws_path)
        print("File:", relative_file)
        print("Docker command:")
        print(command)

        # -----------------------------
        # 4. Execute
        # -----------------------------
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10
            )

        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": "Execution timed out",
                "exit_code": -1,
            }

        except Exception as e:
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
            }

        # -----------------------------
        # 5. Return result
        # -----------------------------
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        print("EXIT CODE:", result.returncode)
        print("=============================\n")

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }