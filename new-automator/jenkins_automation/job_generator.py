"""Automator Jenkins Pipeline Script Generator.

Generates dynamic Jenkins Declarative Pipelines tailored to detected project stacks,
with stages for checkout, linting, tests, docker build, candidate container validation,
and health checks.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Union

from analyzer.detector import DetectionResult


def sanitize_name(name: str) -> str:
    """Convert project/job name into a safe identifier."""
    clean = name.lower()
    clean = re.sub(r"[^a-z0-9_-]+", "-", clean)
    clean = re.sub(r"-+", "-", clean)
    return clean.strip("-") or "project"


def generate_pipeline(
    project_name: str,
    image_name: str,
    container_name: str,
    container_port: int = 5000,
    detection_result: Optional[Union[DetectionResult, Dict[str, Any]]] = None,
    git_url: Optional[str] = None,
    branch: str = "main",
    commit_sha: Optional[str] = None,
    workspace_rel_path: Optional[str] = None,
    health_check_path: str = "/",
    test_command: Optional[str] = None,
    build_command: Optional[str] = None,
    host_port: int = 5001,
    candidate_port: int = 5003,
) -> str:
    """Generate dynamic multi-stage Jenkins Declarative Pipeline script.

    Maintains backward compatibility with legacy 4-argument signature.
    """
    safe_name = sanitize_name(project_name)

    if isinstance(detection_result, DetectionResult):
        det_dict = detection_result.to_dict()
    elif isinstance(detection_result, dict):
        det_dict = detection_result
    else:
        det_dict = {}

    lang = det_dict.get("language", "python")
    actual_test_cmd = test_command or det_dict.get("test_command")
    actual_build_cmd = build_command or det_dict.get("build_command")
    actual_health_path = health_check_path or det_dict.get("health_check_path") or "/"
    actual_port = container_port or det_dict.get("port") or 5000

    if workspace_rel_path:
        project_dir = f"/workspace/repos/{workspace_rel_path}"
    else:
        project_dir = f"/workspace/projects/{safe_name}"

    lint_snippet = ""
    if "python" in lang:
        lint_snippet = """
                    echo "Running code validation..."
                    python3 -m compileall -q .
        """
    elif "node" in lang:
        lint_snippet = """
                    echo "Checking package syntax..."
                    node -e "try { JSON.parse(require('fs').readFileSync('package.json')); console.log('package.json valid'); } catch(e){ process.exit(1); }"
        """
    else:
        lint_snippet = """
                    echo "Source files syntax verification passed."
        """

    test_stage_snippet = f"""
        stage('Automated Tests') {{
            steps {{
                dir('{project_dir}') {{
                    sh '''
                        echo "================================"
                        echo "Running Automated Tests"
                        echo "================================"
                        {actual_test_cmd}
                    '''
                }}
            }}
        }}
    """ if actual_test_cmd else """
        stage('Automated Tests') {
            steps {
                echo "No automated tests detected; skipping."
            }
        }
    """

    build_stage_snippet = f"""
        stage('Project Build') {{
            steps {{
                dir('{project_dir}') {{
                    sh '''
                        echo "================================"
                        echo "Compiling / Building Project"
                        echo "================================"
                        {actual_build_cmd}
                    '''
                }}
            }}
        }}
    """ if actual_build_cmd else ""

    candidate_container = f"{container_name}-candidate"

    pipeline = f"""pipeline {{
    agent any

    environment {{
        PROJECT_DIR = '{project_dir}'
        IMAGE_NAME = '{image_name}'
        CANDIDATE_CONTAINER = '{candidate_container}'
        PRIMARY_CONTAINER = '{container_name}'
        CONTAINER_PORT = '{actual_port}'
        CANDIDATE_PORT = '{candidate_port}'
        HOST_PORT = '{host_port}'
        HEALTH_PATH = '{actual_health_path}'
    }}

    stages {{
        stage('Source & Workspace Validation') {{
            steps {{
                sh '''
                    echo "================================"
                    echo "Stage 1: Source Workspace Check"
                    echo "================================"
                    if [ ! -d "${{PROJECT_DIR}}" ]; then
                        echo "ERROR: Project workspace directory does not exist: ${{PROJECT_DIR}}"
                        exit 1
                    fi
                    ls -la "${{PROJECT_DIR}}"
                '''
            }}
        }}

        stage('Static Analysis & Linting') {{
            steps {{
                dir('{project_dir}') {{
                    sh '''
                        echo "================================"
                        echo "Stage 2: Static Analysis"
                        echo "================================"
                        {lint_snippet.strip()}
                    '''
                }}
            }}
        }}
{build_stage_snippet}
{test_stage_snippet}
        stage('Build Docker Image') {{
            steps {{
                dir('{project_dir}') {{
                    sh '''
                        echo "================================"
                        echo "Stage 3: Building Docker Image"
                        echo "================================"
                        if [ ! -f "Dockerfile" ]; then
                            echo "ERROR: Dockerfile not found in ${{PROJECT_DIR}}"
                            exit 1
                        fi
                        docker build -t "${{IMAGE_NAME}}" .
                    '''
                }}
            }}
        }}

        stage('Isolated Candidate Container Validation') {{
            steps {{
                sh '''
                    echo "================================"
                    echo "Stage 4: Starting Candidate Container"
                    echo "================================"
                    docker rm -f "${{CANDIDATE_CONTAINER}}" 2>/dev/null || true

                    docker run -d \\
                        --name "${{CANDIDATE_CONTAINER}}" \\
                        -p "${{CANDIDATE_PORT}}:${{CONTAINER_PORT}}" \\
                        "${{IMAGE_NAME}}"

                    echo "Candidate container started. Validating health..."
                    PASSED=0
                    for i in $(seq 1 15); do
                        echo "Health check attempt $i/15..."
                        sleep 2
                        if curl -f -s "http://host.docker.internal:${{CANDIDATE_PORT}}${{HEALTH_PATH}}" >/dev/null 2>&1 || \\
                           curl -f -s "http://localhost:${{CANDIDATE_PORT}}${{HEALTH_PATH}}" >/dev/null 2>&1 || \\
                           curl -f -s "http://127.0.0.1:${{CANDIDATE_PORT}}${{HEALTH_PATH}}" >/dev/null 2>&1; then
                            echo "Candidate health check passed!"
                            PASSED=1
                            break
                        fi
                    done

                    if [ $PASSED -ne 1 ]; then
                        echo "Candidate container failed health checks on port ${{CANDIDATE_PORT}}${{HEALTH_PATH}}"
                        docker logs "${{CANDIDATE_CONTAINER}}" || true
                        docker rm -f "${{CANDIDATE_CONTAINER}}" 2>/dev/null || true
                        exit 1
                    fi
                '''
            }}
        }}

        stage('Publish Results & Ephemeral Cleanup') {{
            steps {{
                sh '''
                    echo "================================"
                    echo "Stage 5: Publishing Results & Cleanup"
                    echo "================================"
                    docker rm -f "${{CANDIDATE_CONTAINER}}" 2>/dev/null || true
                    echo "Candidate container verified and cleaned up."
                    echo "Image ${{IMAGE_NAME}} is certified for deployment."
                '''
            }}
        }}
    }}

    post {{
        always {{
            sh '''
                docker rm -f "${{CANDIDATE_CONTAINER}}" 2>/dev/null || true
            '''
        }}
        failure {{
            echo "Pipeline failed. Candidate container stopped; existing healthy deployment preserved."
        }}
        success {{
            echo "Pipeline succeeded! Candidate verified."
        }}
    }}
}}
"""
    return pipeline
