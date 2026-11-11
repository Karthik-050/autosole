# AUTOSOLE CI/CD

Project K contains two FastAPI applications and a Vue web interface:

- **Collaborative Workspace** (`collaborative-workspace/`): project workspaces, editor, Git/versioning, validation, Docker controls, Jenkins controls, and local pipeline runs. Its built Vue interface is served by the API on port **8000**.
- **Standalone Automator CI/CD** (`new-automator/`): repository-based CI/CD dashboard and API on port **8001**. The root launcher starts it alongside the Workspace app.
- **ngrok**: when installed and configured, the root launcher runs `ngrok http 8001` so GitHub can reach the standalone Automator webhook endpoint.

The two applications have separate APIs, settings, and data stores. The Git & Versioning view in the Workspace app is distinct from the standalone Automator repository dashboard.

## Requirements

Install these before setup:

1. **Python 3.10 or newer** (Python 3.14 has been used with this project).
2. **Node.js and npm** (Node 18+; Node 24 has been used) to install and build the Vue interface.
3. **Git**, available on `PATH`, for local repositories and GitHub integration.
4. **Docker Desktop** or Docker Engine for container builds, runs, and sandboxed code execution.
5. **ngrok** on `PATH` and an authenticated ngrok account for public GitHub webhooks. It is optional for local use, but the launcher prints a warning if it is missing.
6. **Jenkins** only if using Jenkins-based builds. The app can run without it, but Jenkins actions will be unavailable.

Ports used by default:

| Service | Port |
| --- | ---: |
| Collaborative Workspace UI/API | 8000 |
| Standalone Automator CI/CD UI/API | 8001 |
| Frontend development server (optional) | 3000 |
| Jenkins (optional) | 8080 |
| Deployment proxy (optional) | 5002 |

Make sure these ports are available before starting the corresponding services.

## First-time setup

Run commands from the repository root (`D:\project next stage` on this machine).

### 1. Configure the Workspace app

Copy the root environment example to `.env` and set values you need. Keep `.env` out of source control.

**Windows PowerShell:**

```powershell
Copy-Item .env.example .env
```

**macOS/Linux:**

```sh
cp .env.example .env
```

At minimum, defaults work for local development. Configure these for integrations:

- `JENKINS_URL`, `JENKINS_USERNAME`, and `JENKINS_API_TOKEN` for Jenkins.
- `GITHUB_JENKINS_CREDENTIAL_ID` if Jenkins needs credentials to clone private repositories.
- `GITHUB_WEBHOOK_SECRET` and `PUBLIC_BASE_URL` if using Workspace GitHub webhooks. Set `PUBLIC_BASE_URL` to the public ngrok HTTPS URL and use the same webhook secret in GitHub.
- `DOCKER_HOST` only if Docker is not using the local default socket/named pipe.

### 2. Configure the standalone Automator

Copy its environment example into the Automator directory:

**Windows PowerShell:**

```powershell
Copy-Item new-automator/.env.example new-automator/.env
```

**macOS/Linux:**

```sh
cp new-automator/.env.example new-automator/.env
```

The root launcher sets `AUTOMATOR_PORT=8001` when it starts the service. Set `AUTOMATOR_JENKINS_URL`, `AUTOMATOR_JENKINS_USERNAME`, and `AUTOMATOR_JENKINS_API_TOKEN` if its builds use Jenkins. Set a stable `AUTOMATOR_GITHUB_WEBHOOK_SECRET` for GitHub webhook verification. Do not commit either `.env` file or put real secrets in the example files.

### 3. Install Python dependencies

The Workspace and standalone Automator have separate requirements files. Install both into the same active Python environment used to run `run.py`:

```sh
python -m pip install --upgrade pip
python -m pip install -r collaborative-workspace/requirements.txt
python -m pip install -r new-automator/requirements.txt
```

On Windows, if `python` does not point to the intended Python installation, use the Python launcher, for example `py -3.12 -m pip ...` for both install commands and `py -3.12 run.py` to start the project.

### 4. Install and build the frontend

```sh
cd collaborative-workspace/frontend
npm ci
npm run build
cd ../..
```

The production build is written to `collaborative-workspace/frontend/dist/`. Rebuild it after frontend changes so the version served on port 8000 is current.

## Start the project

From the repository root:

```sh
python run.py
```

The launcher starts:

- Collaborative Workspace at <http://127.0.0.1:8000/>.
- Standalone Automator CI/CD at <http://127.0.0.1:8001/>.
- `ngrok http 8001`, if the ngrok executable is available.

Open the Automator page directly at port 8001, or use its link in the Workspace app. Stop the services with **Ctrl+C** in the launcher terminal; it also stops the child Automator and ngrok processes.

If the Automator page does not load, check the launcher terminal for its startup error and confirm that port 8001 is unused. If ngrok does not create a tunnel, authenticate ngrok on the machine first. To receive GitHub webhooks, copy the public HTTPS tunnel URL shown by ngrok into the relevant webhook configuration. A free ngrok URL may change between launches.

## Frontend development mode

Keep `python run.py` running in one terminal. In another terminal:

```sh
cd collaborative-workspace/frontend
npm run dev
```

Open <http://127.0.0.1:3000/>. Vite proxies Workspace API requests to port 8000. The standalone Automator page remains at port 8001.

## Optional Jenkins and deployment proxy

The Compose file at `collaborative-workspace/infra/docker-compose.yml` defines Jenkins and a deployment proxy. It expects Docker Compose and external Docker resources named `jenkins_home` and `project-k-deploy`; the Jenkins image mounts the Docker socket and is intended for a Docker host that supports that socket mount. Review the Compose file for your OS before starting these services.

Once the required volume/network exist and the Compose configuration matches your Docker host, start the services from `collaborative-workspace/infra/`:

```sh
docker volume create jenkins_home
docker compose up -d --build
```

Jenkins is exposed at <http://127.0.0.1:8080/> and the deployment proxy at <http://127.0.0.1:5002/>. Configure the app’s Jenkins environment settings to match your Jenkins installation. Docker access is needed by the host app as well as by Jenkins for local builds and deployments.

## Git and CI/CD workflows

### Workspace Git & Versioning

The Git view can initialize local version control, show changes and history, commit, push, or pull a GitHub repository into a Workspace project. **Pull Repository and Start Pipeline** queues a Jenkins job. That repository job checks out the selected branch, uses a basic runtime-detected fallback Dockerfile only when the repository has no Dockerfile, builds an image, starts a candidate container, and performs an HTTP health check. This generation currently uses fixed Python/Node/Java fallbacks; it is not AI-generated. A queued Jenkins job is not proof that its build or deployment succeeded—inspect Jenkins status and logs.

### Workspace pipeline

The top-bar **Run Pipeline** action or **Automator CI/CD** Workspace screen runs the Workspace orchestrator. Depending on selected options, it performs project discovery, Git tracking, code validation, local Docker build or Jenkins build, deployment, and health verification.

### Standalone Automator

The dashboard at port 8001 maintains its own connected-repository records and builds. GitHub webhooks must be configured to target the public ngrok URL at `/webhooks/github` (or the endpoint shown in that dashboard). This data is separate from the Workspace app’s project list.

## API documentation

- Workspace API: <http://127.0.0.1:8000/docs>
- Standalone Automator API: <http://127.0.0.1:8001/docs>

## Tests

The root test command runs the Workspace backend integration/API checks and project detection check:

```sh
python run.py --test
```

The standalone Automator also has its own unittest suite. Run it from its directory:

```sh
cd new-automator
python -m unittest discover -s tests
cd ..
```

## Troubleshooting

- **Port already in use:** stop the process using 8000, 8001, 3000, 8080, or 5002, or change the appropriate setting. `PORT` controls the Workspace app; `AUTOMATOR_PORT` can override the standalone app’s default when launching it directly (the root launcher currently assigns 8001).
- **Automator does not start:** install both requirements files into the Python environment used by `run.py`; inspect the launcher terminal for import or database errors.
- **Automator link opens connection refused:** confirm that the standalone service started and is listening on port 8001.
- **ngrok command fails:** confirm ngrok is installed, authenticated, and not already using a conflicting tunnel/session.
- **Jenkins reports unavailable:** check Jenkins URL, credentials, network access, and that the controller is running.
- **Docker build or preview fails:** confirm Docker is running and inspect build/pipeline logs. A started API or a queued build does not guarantee that an application container is healthy.
- **GitHub webhook does not arrive:** use the current public HTTPS tunnel URL, configure the correct webhook path and event, and ensure the app and GitHub use the same webhook secret.
