# Appendix A: Sample Inputs and Outputs

The following seven examples demonstrate a typical workflow in the Collaborative Workspace project. The responses are representative: generated IDs, timestamps, filesystem paths, and environment-dependent results may differ. The final example requires Docker to be running.

## Sample 1: Create a Python project

**Input**

```http
POST /api/projects
Content-Type: application/json

{
  "name": "Sample Python App",
  "template": "python"
}
```

**Output**

```json
{
  "project": {
    "id": "a1b2c3d4-e5f6-47a8-9b0c-1d2e3f4a5b6c",
    "name": "Sample Python App",
    "path": "<workspace-root>/a1b2c3d4-e5f6-47a8-9b0c-1d2e3f4a5b6c",
    "project_type": "python",
    "framework": "Flask",
    "entrypoint": "app.py",
    "files_count": 2,
    "created_at": "<generated timestamp>",
    "updated_at": "<generated timestamp>"
  },
  "message": "Project created successfully"
}
```

## Sample 2: List project files

**Input**

```http
GET /workspaces/a1b2c3d4-e5f6-47a8-9b0c-1d2e3f4a5b6c/files
```

**Output**

```json
{
  "files": [
    "app.py",
    "requirements.txt"
  ]
}
```

## Sample 3: Write a Python file

**Input**

```http
POST /workspaces/a1b2c3d4-e5f6-47a8-9b0c-1d2e3f4a5b6c/write
```

Query parameters:

```text
filename=hello.py
content=print("Hello from the workspace!")
```

**Output**

```json
{
  "message": "File written successfully"
}
```

## Sample 4: Read the Python file

**Input**

```http
GET /workspaces/a1b2c3d4-e5f6-47a8-9b0c-1d2e3f4a5b6c/read?filename=hello.py
```

**Output**

```json
{
  "content": "print(\"Hello from the workspace!\")"
}
```

## Sample 5: Validate Python code

**Input**

```http
POST /api/validation/a1b2c3d4-e5f6-47a8-9b0c-1d2e3f4a5b6c/validate-file
Content-Type: application/json

{
  "filename": "math_utils.py",
  "content": "def add(a, b):\n    return a + b\n"
}
```

**Output**

```json
{
  "validation": {
    "status": "passed",
    "score": 100,
    "mandatory_checks_passed": true,
    "summary": {
      "errors": 0,
      "warnings": 0,
      "info": 0,
      "total": 0
    },
    "issues": [],
    "test_results": {
      "executed": false,
      "total": 0,
      "passed": 0,
      "failed": 0,
      "details": "No test files detected"
    }
  }
}
```

## Sample 6: Check Git status

**Input**

```http
GET /api/git/a1b2c3d4-e5f6-47a8-9b0c-1d2e3f4a5b6c/status
```

**Output** (after the file-writing sample)

```json
{
  "status": {
    "is_repo": true,
    "branch": "main",
    "clean": false,
    "staged": [],
    "unstaged": [],
    "untracked": [
      "app.py",
      "hello.py",
      "requirements.txt"
    ],
    "commit_count": 0
  }
}
```

## Sample 7: Run the Python file in the sandbox

**Input**

```http
POST /workspaces/a1b2c3d4-e5f6-47a8-9b0c-1d2e3f4a5b6c/run?filename=hello.py
```

**Output** (when Docker is available)

```json
{
  "stdout": "Hello from the workspace!\n",
  "stderr": "",
  "exit_code": 0
}
```

> These are illustrative sample values, not records of a live execution. For formal project evidence, replace the sample IDs and outputs with screenshots or captured responses from your own run.
