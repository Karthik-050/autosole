# AGENTS.md

FastAPI backend + thin CLI for managing "workspaces" (UUID-named dirs under `workspace/`). No tests, lint config, or CI exist.

## Running

- Run all commands from the repo root: imports are root-relative (`from backend.workspace.manager import ...`) and neither package is pip-installed; there is no pyproject.
- Server: `python -m uvicorn backend.main:app --reload`
- CLI: `python -m cli.cli <workspace|file|run> ...` (usage text in `cli/cli.py`; `file write` reads code from stdin until a line `END`). Plain `python cli/cli.py` fails — script-dir `sys.path` breaks the root-relative imports; `-m` adds the CWD instead.
- Frontend dev: `cd frontend && npm run dev` (starts on port 3000, proxies API to `127.0.0.1:8000`). Build for production: `npm run build` (output in `frontend/dist/`).

## Environment gotchas

- `requirements.txt` lists: fastapi, uvicorn[standard], python-dotenv. No `pyproject.toml` or pip-installable package — imports are root-relative.
- The checked-in `venv/` targets Python 3.14 and has packages installed. If it breaks, recreate: `py -3.14 -m venv venv --clear`, then `pip install -r requirements.txt`.

## Architecture notes

- Frontend: Vue 3 + Vite SPA in `frontend/`. Pinia for state, CodeMirror 6 for the editor. Vite dev server proxies `/workspaces*` to the backend on `:8000`.
- All API routes are defined inline in `backend/main.py`. `backend/workspace/routes.py` defines a near-duplicate router but is never imported — editing it changes nothing.
- `backend/workspace/models.py` is an empty placeholder.
- `WorkspaceManager` (backend/workspace/manager.py) resolves `workspace/` relative to its own file location, not the CWD.
- `workspace/<uuid>/` holds real user data — don't delete or commit its contents.
- Code execution goes through `SandboxRunner` (sandbox/runner.py), which shells out to Docker (`python:3.10-slim`, workspace bind-mounted at `/app`) and returns `{stdout, stderr, exit_code}`. Requires a running Docker daemon. Not hardened yet: no timeout/CPU/memory/network limits.

## Hygiene

- `.gitignore` is currently empty; keep `venv/`, `__pycache__/`, `.idea/`, and `workspace/` out of commits.
