# Collaborative Workspace & Automator (Integrated Platform)

FastAPI backend + CLI + Vue 3 SPA for managing code workspaces, code validation, Git version control, Docker workloads, and Jenkins pipelines.

## Prerequisites

- Python 3.10+ (tested with Python 3.14)
- Node.js 18+ (tested with Node 24)
- Docker Desktop (for container builds and sandbox execution)
- Jenkins Controller (optional, for remote CI/CD)

## Quick Start

```bash
# Start backend and serve frontend UI:
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# Or from root directory:
python run.py
```

- Web Dashboard & Workspace: `http://127.0.0.1:8000/`
- Interactive API Docs: `http://127.0.0.1:8000/docs`

## Frontend Development

```bash
cd frontend
npm run dev
# Starts on port 3000, proxies /api and /workspaces to 127.0.0.1:8000
```

## Running CLI

```bash
# Workspace management
python -m cli.cli workspace create
python -m cli.cli workspace list
python -m cli.cli workspace delete <workspace_id>

# File operations
python -m cli.cli file create <workspace_id> <filename>
python -m cli.cli file write <workspace_id> <filename>
python -m cli.cli file read <workspace_id> <filename>
python -m cli.cli file delete <workspace_id> <filename>
python -m cli.cli file list <workspace_id>

# Run code in sandbox
python -m cli.cli run <workspace_id> <filename>
```

## Testing

```bash
# Run all tests:
python -m unittest tests/test_backend_integration.py
python -m unittest tests/test_api_endpoints.py
python test_project_detect.py
```

## API Endpoints

### Legacy Workspace Endpoints (100% Preserved)
- `GET /` - Health check & UI
- `POST /workspaces` - Create workspace
- `GET /workspaces` - List workspaces
- `DELETE /workspaces/{id}` - Delete workspace
- `POST /workspaces/{id}/files` - Create file
- `GET /workspaces/{id}/files` - List files
- `POST /workspaces/{id}/write` - Write file
- `GET /workspaces/{id}/read` - Read file
- `DELETE /workspaces/{id}/files` - Delete file
- `POST /workspaces/{id}/run` - Run Python file in sandbox

### Modular Unified APIs
- `GET /api/dashboard/stats` - System overview and active project metrics
- `GET /api/projects` - Detailed projects list with templates and detection
- `POST /api/projects/import-automator-test` - Import Automator test project archive
- `GET /api/git/{id}/status` - Git branch, modified, staged, and untracked files
- `POST /api/git/{id}/commit` - Commit changes
- `GET /api/git/{id}/history` - Git commit log
- `GET /api/git/{id}/diff` - Working tree diff
- `GET /api/validation/{id}/scan` - Full code validation with syntax, security, and tests
- `GET /api/docker/status` - Docker daemon health
- `POST /api/docker/{id}/dockerfile` - Generate or edit Dockerfile
- `POST /api/docker/{id}/build` - Build Docker image
- `GET /api/docker/containers` - List containers
- `GET /api/jenkins/status` - Jenkins controller status
- `GET /api/jenkins/jobs` - List Jenkins jobs
- `POST /api/jenkins/jobs/{job}/trigger` - Trigger Jenkins build
- `POST /api/pipeline/trigger` - Trigger end-to-end CI/CD workflow
- `GET /api/pipeline/runs` - List pipeline runs with stage progress
- `GET /api/deployments` - List active deployments
- `POST /api/deployments/{id}/health` - Run HTTP health probe
- `GET /api/settings` - Masked system settings
- `POST /api/settings` - Update configuration

## Jenkins GitHub push deployments

Jenkins and the blue-green reverse proxy are defined in `infra/docker-compose.yml`. Start them from the Collaborative Workspace directory with:

```powershell
docker compose -f infra/docker-compose.yml up -d --build
```

The Compose setup reuses the existing `jenkins_home` Docker volume, publishes Jenkins at `http://localhost:8080`, and publishes the deployment proxy at `http://localhost:5002`. The previous direct deployment on port 5001 is left untouched. Complete Jenkins' first-run setup if needed, ensure the Git and Pipeline plugins are installed, create an API token, then set the matching `JENKINS_USERNAME` and `JENKINS_API_TOKEN` in `.env` and restart Project K before connecting repositories.

Connecting a GitHub repository creates a Jenkins Pipeline job and queues its first build. The job checks out the selected branch, builds a candidate image, starts a candidate container, and probes it before changing the Nginx upstream. Nginx reloads gracefully; the previous container stays running until after the switch and is then stopped with a 120-second grace period. Failed candidate health checks or Nginx configuration checks leave the previous upstream in place. Each project is served at `http://<project-id>.localhost:5002`.

To trigger builds on pushes, configure `GITHUB_WEBHOOK_SECRET` and a public HTTPS `PUBLIC_BASE_URL` in `.env`, restart the workspace app, then register `https://<public-host>/api/webhooks/github` in the repository's GitHub Webhooks settings with the same secret and the `push` event. GitHub cannot deliver to a localhost URL. The endpoint verifies GitHub's SHA-256 HMAC signature and only queues a Jenkins job for the repository and branch connected to a workspace. For private repositories, configure a Jenkins username/password credential and set its ID in `GITHUB_JENKINS_CREDENTIAL_ID`.

Jenkins is granted Docker socket access so its jobs can build and run containers. Restrict Jenkins access and only connect repositories whose code you trust.
