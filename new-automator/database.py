"""SQLite persistence layer for Automator CI/CD.

Provides schema initialization, migration tracking, and asynchronous CRUD operations
for repositories, builds, webhook deliveries, and deployments using aiosqlite.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Union

import aiosqlite

from config import get_settings

logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS AND SCHEMA DEFINITIONS
# ============================================================

REPOSITORY_BOOL_FIELDS: Set[str] = {"is_private"}
BUILD_BOOL_FIELDS: Set[str] = {"health_check_passed"}
WEBHOOK_BOOL_FIELDS: Set[str] = {"processed"}
DEPLOYMENT_BOOL_FIELDS: Set[str] = {"is_healthy", "is_current"}

JSON_FIELDS: Set[str] = {
    "detected_stack",
    "test_summary",
    "payload_summary",
}

# Whitelist for update operations to ensure strict SQL safety
REPOSITORY_ALLOWED_UPDATE_FIELDS: Set[str] = {
    "url",
    "provider",
    "name",
    "owner",
    "default_branch",
    "is_private",
    "credential_id",
    "webhook_secret",
    "webhook_id",
    "jenkins_job_name",
    "status",
}

BUILD_ALLOWED_UPDATE_FIELDS: Set[str] = {
    "commit_sha",
    "commit_message",
    "branch",
    "trigger_type",
    "pr_number",
    "status",
    "detected_stack",
    "dockerfile_source",
    "docker_image_tag",
    "jenkins_build_number",
    "jenkins_queue_id",
    "test_summary",
    "health_check_passed",
    "container_id",
    "error_message",
    "started_at",
    "completed_at",
    "duration_seconds",
    "log_path",
}

WEBHOOK_ALLOWED_UPDATE_FIELDS: Set[str] = {
    "repository_id",
    "event_type",
    "action",
    "commit_sha",
    "branch",
    "pr_number",
    "payload_summary",
    "processed",
    "build_id",
    "received_at",
    "processed_at",
}

DEPLOYMENT_ALLOWED_UPDATE_FIELDS: Set[str] = {
    "repository_id",
    "build_id",
    "container_name",
    "container_id",
    "image_tag",
    "host_port",
    "container_port",
    "status",
    "is_healthy",
    "is_current",
    "health_check_url",
    "stopped_at",
}

# Ordered database migrations (version, description, SQL)
MIGRATIONS: List[tuple[int, str, str]] = [
    (
        1,
        "initial_schema",
        """
        CREATE TABLE IF NOT EXISTS repositories (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            provider TEXT NOT NULL,
            name TEXT NOT NULL,
            owner TEXT NOT NULL,
            default_branch TEXT NOT NULL DEFAULT 'main',
            is_private INTEGER NOT NULL DEFAULT 0,
            credential_id TEXT,
            webhook_secret TEXT,
            webhook_id TEXT,
            jenkins_job_name TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        );

        CREATE INDEX IF NOT EXISTS idx_repositories_url ON repositories(url);
        CREATE INDEX IF NOT EXISTS idx_repositories_owner_name ON repositories(owner, name);
        CREATE INDEX IF NOT EXISTS idx_repositories_status ON repositories(status);

        CREATE TABLE IF NOT EXISTS builds (
            id TEXT PRIMARY KEY,
            repository_id TEXT NOT NULL,
            build_number INTEGER NOT NULL,
            commit_sha TEXT NOT NULL,
            commit_message TEXT,
            branch TEXT NOT NULL,
            trigger_type TEXT NOT NULL DEFAULT 'manual',
            pr_number INTEGER,
            status TEXT NOT NULL DEFAULT 'queued',
            detected_stack TEXT,
            dockerfile_source TEXT,
            docker_image_tag TEXT,
            jenkins_build_number INTEGER,
            jenkins_queue_id INTEGER,
            test_summary TEXT,
            health_check_passed INTEGER DEFAULT 0,
            container_id TEXT,
            error_message TEXT,
            started_at TEXT,
            completed_at TEXT,
            duration_seconds REAL,
            log_path TEXT,
            FOREIGN KEY (repository_id) REFERENCES repositories(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_builds_repo_id ON builds(repository_id);
        CREATE INDEX IF NOT EXISTS idx_builds_status ON builds(status);
        CREATE INDEX IF NOT EXISTS idx_builds_repo_number ON builds(repository_id, build_number);
        CREATE INDEX IF NOT EXISTS idx_builds_commit_sha ON builds(commit_sha);

        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id TEXT PRIMARY KEY,
            repository_id TEXT,
            event_type TEXT NOT NULL,
            action TEXT,
            commit_sha TEXT,
            branch TEXT,
            pr_number INTEGER,
            payload_summary TEXT,
            processed INTEGER NOT NULL DEFAULT 0,
            build_id TEXT,
            received_at TEXT NOT NULL,
            processed_at TEXT,
            FOREIGN KEY (repository_id) REFERENCES repositories(id) ON DELETE SET NULL,
            FOREIGN KEY (build_id) REFERENCES builds(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_webhooks_repo_id ON webhook_deliveries(repository_id);
        CREATE INDEX IF NOT EXISTS idx_webhooks_processed ON webhook_deliveries(processed);

        CREATE TABLE IF NOT EXISTS deployments (
            id TEXT PRIMARY KEY,
            repository_id TEXT NOT NULL,
            build_id TEXT,
            container_name TEXT,
            container_id TEXT,
            image_tag TEXT,
            host_port INTEGER,
            status TEXT NOT NULL DEFAULT 'running',
            is_healthy INTEGER NOT NULL DEFAULT 0,
            is_current INTEGER NOT NULL DEFAULT 0,
            health_check_url TEXT,
            created_at TEXT NOT NULL,
            stopped_at TEXT,
            FOREIGN KEY (repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
            FOREIGN KEY (build_id) REFERENCES builds(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_deployments_repo_id ON deployments(repository_id);
        CREATE INDEX IF NOT EXISTS idx_deployments_current ON deployments(repository_id, is_current);
        CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status);
        """,
    ),
    (
        2,
        "add_container_port_to_deployments",
        """
        ALTER TABLE deployments ADD COLUMN container_port INTEGER DEFAULT 5000;
        """,
    ),
]


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def utc_now_iso() -> str:
    """Return the current UTC timestamp formatted as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def serialize_json_field(value: Any) -> Optional[str]:
    """Serialize a dict or list to a JSON string if needed."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, str):
        return value
    return str(value)


def row_to_dict(
    row: Optional[aiosqlite.Row],
    bool_fields: Optional[Set[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Convert an aiosqlite.Row into a standard dictionary with proper types.

    Args:
        row: The SQLite row object, or None.
        bool_fields: Set of column names that should be cast to boolean.

    Returns:
        Dict representing row contents, or None if row is None.
    """
    if row is None:
        return None

    data = dict(row)

    if bool_fields:
        for field in bool_fields:
            if field in data and data[field] is not None:
                data[field] = bool(data[field])

    for json_col in JSON_FIELDS:
        if json_col in data and isinstance(data[json_col], str):
            try:
                data[json_col] = json.loads(data[json_col])
            except (json.JSONDecodeError, TypeError):
                pass

    return data


def rows_to_dicts(
    rows: List[aiosqlite.Row],
    bool_fields: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Convert a list of aiosqlite.Row objects into a list of dictionaries."""
    result: List[Dict[str, Any]] = []
    for r in rows:
        d = row_to_dict(r, bool_fields)
        if d is not None:
            result.append(d)
    return result


def resolve_db_path(db_path: Optional[Union[Path, str]] = None) -> Union[Path, str]:
    """Resolve database path, falling back to configured settings if not provided."""
    if db_path is not None:
        return db_path
    settings = get_settings()
    return settings.DB_PATH or (settings.BASE_DIR / "automator.db")


# ============================================================
# CONNECTION MANAGEMENT
# ============================================================

@asynccontextmanager
async def get_connection(
    db_path: Optional[Union[Path, str]] = None,
) -> AsyncIterator[aiosqlite.Connection]:
    """Provide an asynchronous SQLite database connection with row factory and WAL mode.

    Args:
        db_path: Optional path to the SQLite file. If omitted, uses Settings.DB_PATH.

    Yields:
        aiosqlite.Connection configured with foreign keys and WAL journal mode.
    """
    path = resolve_db_path(db_path)
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(path)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute("PRAGMA journal_mode = WAL;")
        yield conn


@asynccontextmanager
async def _get_conn(
    conn: Optional[aiosqlite.Connection] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> AsyncIterator[aiosqlite.Connection]:
    """Internal helper to either reuse an active connection or open a new one.

    If a new connection is created, it will be automatically committed upon completion.
    """
    if conn is not None:
        yield conn
    else:
        async with get_connection(db_path) as new_conn:
            yield new_conn
            await new_conn.commit()


# ============================================================
# DATABASE INITIALIZATION AND MIGRATIONS
# ============================================================

async def apply_migrations(conn: aiosqlite.Connection) -> None:
    """Apply pending schema migrations in version sequence.

    Args:
        conn: Open aiosqlite database connection.
    """
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );
        """
    )
    await conn.commit()

    async with conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version ASC;"
    ) as cursor:
        rows = await cursor.fetchall()
        applied_versions = {row[0] for row in rows}

    for version, name, script in MIGRATIONS:
        if version not in applied_versions:
            logger.info("Applying database migration %d: %s", version, name)
            await conn.executescript(script)
            await conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?);",
                (version, name, utc_now_iso()),
            )
            await conn.commit()
            logger.info("Database migration %d (%s) applied successfully.", version, name)


async def init_db(db_path: Optional[Union[Path, str]] = None) -> None:
    """Initialize SQLite database, ensuring tables, indexes, and migrations are applied.

    Args:
        db_path: Optional path to SQLite file. If omitted, uses Settings.DB_PATH.
    """
    path = resolve_db_path(db_path)
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(path)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute("PRAGMA journal_mode = WAL;")
        await apply_migrations(conn)


# ============================================================
# REPOSITORY CRUD OPERATIONS
# ============================================================

async def create_repository(
    url: str,
    provider: str,
    name: str,
    owner: str,
    default_branch: str = "main",
    is_private: bool = False,
    credential_id: Optional[str] = None,
    webhook_secret: Optional[str] = None,
    webhook_id: Optional[str] = None,
    jenkins_job_name: Optional[str] = None,
    status: str = "active",
    repo_id: Optional[str] = None,
    conn: Optional[aiosqlite.Connection] = None,
) -> Dict[str, Any]:
    """Create a new repository record in the database.

    Args:
        url: Clone URL or remote URL of the repository.
        provider: Git provider (e.g. 'github', 'gitlab', 'bitbucket').
        name: Name of the repository.
        owner: Owner or organization name.
        default_branch: Default git branch.
        is_private: True if private repository.
        credential_id: Credential identifier reference.
        webhook_secret: Shared secret for webhook signature verification.
        webhook_id: External webhook ID from provider.
        jenkins_job_name: Corresponding Jenkins job name.
        status: Repository status ('active', 'disconnected', 'error').
        repo_id: Optional UUID. Generated if not supplied.
        conn: Optional active database connection.

    Returns:
        Dict of the created repository record.
    """
    final_id = repo_id or str(uuid.uuid4())
    now = utc_now_iso()

    async with _get_conn(conn) as c:
        await c.execute(
            """
            INSERT INTO repositories (
                id, url, provider, name, owner, default_branch, is_private,
                credential_id, webhook_secret, webhook_id, jenkins_job_name,
                created_at, updated_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                final_id,
                url,
                provider,
                name,
                owner,
                default_branch,
                1 if is_private else 0,
                credential_id,
                webhook_secret,
                webhook_id,
                jenkins_job_name,
                now,
                now,
                status,
            ),
        )

        async with c.execute("SELECT * FROM repositories WHERE id = ?;", (final_id,)) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, REPOSITORY_BOOL_FIELDS) or {}


async def get_repository(
    repo_id: str,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a repository by its unique identifier."""
    async with _get_conn(conn) as c:
        async with c.execute("SELECT * FROM repositories WHERE id = ?;", (repo_id,)) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, REPOSITORY_BOOL_FIELDS)


async def get_repository_by_url(
    url: str,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a repository by its remote URL."""
    async with _get_conn(conn) as c:
        async with c.execute("SELECT * FROM repositories WHERE url = ?;", (url,)) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, REPOSITORY_BOOL_FIELDS)


async def get_repository_by_name(
    owner: str,
    name: str,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a repository by owner and repository name."""
    async with _get_conn(conn) as c:
        async with c.execute(
            "SELECT * FROM repositories WHERE owner = ? AND name = ?;",
            (owner, name),
        ) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, REPOSITORY_BOOL_FIELDS)


async def list_repositories(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    conn: Optional[aiosqlite.Connection] = None,
) -> List[Dict[str, Any]]:
    """List repositories with optional status filtering and pagination."""
    query = "SELECT * FROM repositories"
    params: List[Any] = []

    if status is not None:
        query += " WHERE status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    async with _get_conn(conn) as c:
        async with c.execute(query, params) as cur:
            rows = await cur.fetchall()
            return rows_to_dicts(rows, REPOSITORY_BOOL_FIELDS)


async def update_repository(
    repo_id: str,
    conn: Optional[aiosqlite.Connection] = None,
    **fields: Any,
) -> Optional[Dict[str, Any]]:
    """Update fields of an existing repository record.

    Args:
        repo_id: Unique repository ID.
        conn: Optional active database connection.
        **fields: Keyword arguments of fields to update.

    Returns:
        Updated repository record dict, or None if record not found.

    Raises:
        ValueError: If an unallowed field name is passed.
    """
    if not fields:
        return await get_repository(repo_id, conn)

    clauses: List[str] = []
    params: List[Any] = []

    for key, value in fields.items():
        if key not in REPOSITORY_ALLOWED_UPDATE_FIELDS:
            raise ValueError(f"Disallowed field for repository update: {key}")

        if key == "is_private":
            value = 1 if value else 0

        clauses.append(f"{key} = ?")
        params.append(value)

    clauses.append("updated_at = ?")
    params.append(utc_now_iso())

    params.append(repo_id)
    sql = f"UPDATE repositories SET {', '.join(clauses)} WHERE id = ?;"

    async with _get_conn(conn) as c:
        await c.execute(sql, params)
        async with c.execute("SELECT * FROM repositories WHERE id = ?;", (repo_id,)) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, REPOSITORY_BOOL_FIELDS)


async def delete_repository(
    repo_id: str,
    conn: Optional[aiosqlite.Connection] = None,
) -> bool:
    """Delete a repository and cascade related builds and deployments.

    Returns:
        True if repository was deleted, False if not found.
    """
    async with _get_conn(conn) as c:
        cursor = await c.execute("DELETE FROM repositories WHERE id = ?;", (repo_id,))
        return cursor.rowcount > 0


# ============================================================
# BUILD CRUD OPERATIONS
# ============================================================

async def create_build(
    repository_id: str,
    commit_sha: str,
    branch: str,
    commit_message: Optional[str] = None,
    trigger_type: str = "manual",
    pr_number: Optional[int] = None,
    status: str = "queued",
    detected_stack: Optional[Union[Dict[str, Any], List[Any], str]] = None,
    dockerfile_source: Optional[str] = None,
    docker_image_tag: Optional[str] = None,
    jenkins_build_number: Optional[int] = None,
    jenkins_queue_id: Optional[int] = None,
    test_summary: Optional[Union[Dict[str, Any], List[Any], str]] = None,
    health_check_passed: bool = False,
    container_id: Optional[str] = None,
    error_message: Optional[str] = None,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    log_path: Optional[str] = None,
    build_number: Optional[int] = None,
    build_id: Optional[str] = None,
    conn: Optional[aiosqlite.Connection] = None,
) -> Dict[str, Any]:
    """Create a new build record. Auto-assigns consecutive build number if not provided."""
    final_id = build_id or str(uuid.uuid4())

    async with _get_conn(conn) as c:
        if build_number is None:
            async with c.execute(
                "SELECT COALESCE(MAX(build_number), 0) + 1 FROM builds WHERE repository_id = ?;",
                (repository_id,),
            ) as cur:
                row = await cur.fetchone()
                assigned_number = row[0] if row else 1
        else:
            assigned_number = build_number

        serialized_stack = serialize_json_field(detected_stack)
        serialized_test = serialize_json_field(test_summary)

        await c.execute(
            """
            INSERT INTO builds (
                id, repository_id, build_number, commit_sha, commit_message,
                branch, trigger_type, pr_number, status, detected_stack,
                dockerfile_source, docker_image_tag, jenkins_build_number,
                jenkins_queue_id, test_summary, health_check_passed,
                container_id, error_message, started_at, completed_at,
                duration_seconds, log_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                final_id,
                repository_id,
                assigned_number,
                commit_sha,
                commit_message,
                branch,
                trigger_type,
                pr_number,
                status,
                serialized_stack,
                dockerfile_source,
                docker_image_tag,
                jenkins_build_number,
                jenkins_queue_id,
                serialized_test,
                1 if health_check_passed else 0,
                container_id,
                error_message,
                started_at,
                completed_at,
                duration_seconds,
                log_path,
            ),
        )

        async with c.execute("SELECT * FROM builds WHERE id = ?;", (final_id,)) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, BUILD_BOOL_FIELDS) or {}


async def get_build(
    build_id: str,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a build record by its unique ID."""
    async with _get_conn(conn) as c:
        async with c.execute("SELECT * FROM builds WHERE id = ?;", (build_id,)) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, BUILD_BOOL_FIELDS)


async def get_build_by_number(
    repo_id: str,
    build_number: int,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a build record by repository ID and build number."""
    async with _get_conn(conn) as c:
        async with c.execute(
            "SELECT * FROM builds WHERE repository_id = ? AND build_number = ?;",
            (repo_id, build_number),
        ) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, BUILD_BOOL_FIELDS)


async def list_builds(
    repo_id: Optional[str] = None,
    status: Optional[str] = None,
    branch: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    conn: Optional[aiosqlite.Connection] = None,
) -> List[Dict[str, Any]]:
    """List build records with optional filtering by repo, status, or branch."""
    conditions: List[str] = []
    params: List[Any] = []

    if repo_id is not None:
        conditions.append("repository_id = ?")
        params.append(repo_id)

    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    if branch is not None:
        conditions.append("branch = ?")
        params.append(branch)

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM builds{where_clause} ORDER BY build_number DESC, started_at DESC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    async with _get_conn(conn) as c:
        async with c.execute(query, params) as cur:
            rows = await cur.fetchall()
            return rows_to_dicts(rows, BUILD_BOOL_FIELDS)


async def update_build(
    build_id: str,
    conn: Optional[aiosqlite.Connection] = None,
    **fields: Any,
) -> Optional[Dict[str, Any]]:
    """Update fields on an existing build record.

    Args:
        build_id: Build identifier.
        conn: Optional active database connection.
        **fields: Keyword arguments of fields to update.

    Returns:
        Updated build record dict, or None if record not found.

    Raises:
        ValueError: If an unallowed field name is passed.
    """
    if not fields:
        return await get_build(build_id, conn)

    clauses: List[str] = []
    params: List[Any] = []

    for key, value in fields.items():
        if key not in BUILD_ALLOWED_UPDATE_FIELDS:
            raise ValueError(f"Disallowed field for build update: {key}")

        if key in JSON_FIELDS:
            value = serialize_json_field(value)
        elif key == "health_check_passed":
            value = 1 if value else 0

        clauses.append(f"{key} = ?")
        params.append(value)

    params.append(build_id)
    sql = f"UPDATE builds SET {', '.join(clauses)} WHERE id = ?;"

    async with _get_conn(conn) as c:
        await c.execute(sql, params)
        async with c.execute("SELECT * FROM builds WHERE id = ?;", (build_id,)) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, BUILD_BOOL_FIELDS)


async def delete_build(
    build_id: str,
    conn: Optional[aiosqlite.Connection] = None,
) -> bool:
    """Delete a build record.

    Returns:
        True if build was deleted, False if not found.
    """
    async with _get_conn(conn) as c:
        cursor = await c.execute("DELETE FROM builds WHERE id = ?;", (build_id,))
        return cursor.rowcount > 0


async def get_latest_successful_build(
    repo_id: str,
    branch: Optional[str] = None,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve the most recent successful build for a given repository and optional branch.

    Args:
        repo_id: Unique repository ID.
        branch: Optional branch name filter.
        conn: Optional active database connection.

    Returns:
        Dict of the latest successful build, or None if none found.
    """
    query = "SELECT * FROM builds WHERE repository_id = ? AND status = 'success'"
    params: List[Any] = [repo_id]

    if branch is not None:
        query += " AND branch = ?"
        params.append(branch)

    query += " ORDER BY build_number DESC, completed_at DESC LIMIT 1;"

    async with _get_conn(conn) as c:
        async with c.execute(query, params) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, BUILD_BOOL_FIELDS)


# ============================================================
# WEBHOOK DELIVERY CRUD OPERATIONS
# ============================================================

async def create_webhook_delivery(
    delivery_id: str,
    event_type: str,
    repository_id: Optional[str] = None,
    action: Optional[str] = None,
    commit_sha: Optional[str] = None,
    branch: Optional[str] = None,
    pr_number: Optional[int] = None,
    payload_summary: Optional[Union[Dict[str, Any], List[Any], str]] = None,
    processed: bool = False,
    build_id: Optional[str] = None,
    received_at: Optional[str] = None,
    processed_at: Optional[str] = None,
    conn: Optional[aiosqlite.Connection] = None,
) -> Dict[str, Any]:
    """Record an incoming webhook delivery event."""
    final_received_at = received_at or utc_now_iso()
    serialized_payload = serialize_json_field(payload_summary)

    async with _get_conn(conn) as c:
        await c.execute(
            """
            INSERT INTO webhook_deliveries (
                id, repository_id, event_type, action, commit_sha,
                branch, pr_number, payload_summary, processed, build_id,
                received_at, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                delivery_id,
                repository_id,
                event_type,
                action,
                commit_sha,
                branch,
                pr_number,
                serialized_payload,
                1 if processed else 0,
                build_id,
                final_received_at,
                processed_at,
            ),
        )

        async with c.execute(
            "SELECT * FROM webhook_deliveries WHERE id = ?;", (delivery_id,)
        ) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, WEBHOOK_BOOL_FIELDS) or {}


async def get_webhook_delivery(
    delivery_id: str,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a webhook delivery event by delivery ID."""
    async with _get_conn(conn) as c:
        async with c.execute(
            "SELECT * FROM webhook_deliveries WHERE id = ?;", (delivery_id,)
        ) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, WEBHOOK_BOOL_FIELDS)


async def list_webhook_deliveries(
    repo_id: Optional[str] = None,
    processed: Optional[bool] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    conn: Optional[aiosqlite.Connection] = None,
) -> List[Dict[str, Any]]:
    """List webhook delivery records with optional filters."""
    conditions: List[str] = []
    params: List[Any] = []

    if repo_id is not None:
        conditions.append("repository_id = ?")
        params.append(repo_id)

    if processed is not None:
        conditions.append("processed = ?")
        params.append(1 if processed else 0)

    if event_type is not None:
        conditions.append("event_type = ?")
        params.append(event_type)

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM webhook_deliveries{where_clause} ORDER BY received_at DESC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    async with _get_conn(conn) as c:
        async with c.execute(query, params) as cur:
            rows = await cur.fetchall()
            return rows_to_dicts(rows, WEBHOOK_BOOL_FIELDS)


async def mark_webhook_processed(
    delivery_id: str,
    build_id: Optional[str] = None,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Mark a webhook delivery event as processed, optionally linking the triggered build."""
    now = utc_now_iso()
    async with _get_conn(conn) as c:
        await c.execute(
            """
            UPDATE webhook_deliveries
            SET processed = 1, processed_at = ?, build_id = COALESCE(?, build_id)
            WHERE id = ?;
            """,
            (now, build_id, delivery_id),
        )
        async with c.execute(
            "SELECT * FROM webhook_deliveries WHERE id = ?;", (delivery_id,)
        ) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, WEBHOOK_BOOL_FIELDS)


async def update_webhook_delivery(
    delivery_id: str,
    conn: Optional[aiosqlite.Connection] = None,
    **fields: Any,
) -> Optional[Dict[str, Any]]:
    """Update fields on an existing webhook delivery record."""
    if not fields:
        return await get_webhook_delivery(delivery_id, conn)

    clauses: List[str] = []
    params: List[Any] = []

    for key, value in fields.items():
        if key not in WEBHOOK_ALLOWED_UPDATE_FIELDS:
            raise ValueError(f"Disallowed field for webhook update: {key}")

        if key == "payload_summary":
            value = serialize_json_field(value)
        elif key == "processed":
            value = 1 if value else 0

        clauses.append(f"{key} = ?")
        params.append(value)

    params.append(delivery_id)
    sql = f"UPDATE webhook_deliveries SET {', '.join(clauses)} WHERE id = ?;"

    async with _get_conn(conn) as c:
        await c.execute(sql, params)
        async with c.execute(
            "SELECT * FROM webhook_deliveries WHERE id = ?;", (delivery_id,)
        ) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, WEBHOOK_BOOL_FIELDS)


# ============================================================
# DEPLOYMENT CRUD OPERATIONS
# ============================================================

async def create_deployment(
    repository_id: str,
    build_id: Optional[str] = None,
    container_name: Optional[str] = None,
    container_id: Optional[str] = None,
    image_tag: Optional[str] = None,
    host_port: Optional[int] = None,
    container_port: Optional[int] = 5000,
    status: str = "running",
    is_healthy: bool = False,
    is_current: bool = False,
    health_check_url: Optional[str] = None,
    created_at: Optional[str] = None,
    stopped_at: Optional[str] = None,
    deployment_id: Optional[str] = None,
    conn: Optional[aiosqlite.Connection] = None,
) -> Dict[str, Any]:
    """Create a new deployment record.

    If is_current is True, existing deployments for this repository are marked not current.
    """
    final_id = deployment_id or str(uuid.uuid4())
    final_created_at = created_at or utc_now_iso()

    async with _get_conn(conn) as c:
        if is_current:
            await c.execute(
                "UPDATE deployments SET is_current = 0 WHERE repository_id = ?;",
                (repository_id,),
            )

        await c.execute(
            """
            INSERT INTO deployments (
                id, repository_id, build_id, container_name, container_id,
                image_tag, host_port, container_port, status, is_healthy, is_current,
                health_check_url, created_at, stopped_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                final_id,
                repository_id,
                build_id,
                container_name,
                container_id,
                image_tag,
                host_port,
                container_port,
                status,
                1 if is_healthy else 0,
                1 if is_current else 0,
                health_check_url,
                final_created_at,
                stopped_at,
            ),
        )

        async with c.execute("SELECT * FROM deployments WHERE id = ?;", (final_id,)) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, DEPLOYMENT_BOOL_FIELDS) or {}


async def get_deployment(
    deployment_id: str,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve a deployment record by its unique identifier."""
    async with _get_conn(conn) as c:
        async with c.execute("SELECT * FROM deployments WHERE id = ?;", (deployment_id,)) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, DEPLOYMENT_BOOL_FIELDS)


async def list_deployments(
    repo_id: Optional[str] = None,
    status: Optional[str] = None,
    is_current: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    conn: Optional[aiosqlite.Connection] = None,
) -> List[Dict[str, Any]]:
    """List deployment records with optional filters."""
    conditions: List[str] = []
    params: List[Any] = []

    if repo_id is not None:
        conditions.append("repository_id = ?")
        params.append(repo_id)

    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    if is_current is not None:
        conditions.append("is_current = ?")
        params.append(1 if is_current else 0)

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM deployments{where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    async with _get_conn(conn) as c:
        async with c.execute(query, params) as cur:
            rows = await cur.fetchall()
            return rows_to_dicts(rows, DEPLOYMENT_BOOL_FIELDS)


async def update_deployment(
    deployment_id: str,
    conn: Optional[aiosqlite.Connection] = None,
    **fields: Any,
) -> Optional[Dict[str, Any]]:
    """Update fields on an existing deployment record.

    If is_current is being set to True, all other deployments for this repository
    are automatically marked is_current = 0.
    """
    if not fields:
        return await get_deployment(deployment_id, conn)

    async with _get_conn(conn) as c:
        # Retrieve current record to know repository_id if is_current is being updated
        if "is_current" in fields and fields["is_current"]:
            async with c.execute(
                "SELECT repository_id FROM deployments WHERE id = ?;", (deployment_id,)
            ) as cur:
                existing = await cur.fetchone()
                if existing:
                    repo_id = existing[0]
                    await c.execute(
                        "UPDATE deployments SET is_current = 0 WHERE repository_id = ?;",
                        (repo_id,),
                    )

        clauses: List[str] = []
        params: List[Any] = []

        for key, value in fields.items():
            if key not in DEPLOYMENT_ALLOWED_UPDATE_FIELDS:
                raise ValueError(f"Disallowed field for deployment update: {key}")

            if key in {"is_healthy", "is_current"}:
                value = 1 if value else 0

            clauses.append(f"{key} = ?")
            params.append(value)

        params.append(deployment_id)
        sql = f"UPDATE deployments SET {', '.join(clauses)} WHERE id = ?;"

        await c.execute(sql, params)
        async with c.execute("SELECT * FROM deployments WHERE id = ?;", (deployment_id,)) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, DEPLOYMENT_BOOL_FIELDS)


async def set_current_deployment(
    repo_id: str,
    deployment_id: str,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Set the active current deployment for a repository atomically.

    Demotes any other current deployment for the given repository.

    Args:
        repo_id: Unique repository ID.
        deployment_id: Unique deployment ID to make active.
        conn: Optional active database connection.

    Returns:
        Updated deployment record, or None if deployment was not found.
    """
    async with _get_conn(conn) as c:
        await c.execute(
            "UPDATE deployments SET is_current = 0 WHERE repository_id = ?;",
            (repo_id,),
        )
        cursor = await c.execute(
            "UPDATE deployments SET is_current = 1 WHERE id = ? AND repository_id = ?;",
            (deployment_id, repo_id),
        )
        if cursor.rowcount == 0:
            return None

        async with c.execute("SELECT * FROM deployments WHERE id = ?;", (deployment_id,)) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, DEPLOYMENT_BOOL_FIELDS)


async def get_current_deployment(
    repo_id: str,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve the currently active deployment for a repository.

    Args:
        repo_id: Unique repository ID.
        conn: Optional active database connection.

    Returns:
        Active deployment dict with is_current=True, or None if none active.
    """
    async with _get_conn(conn) as c:
        async with c.execute(
            "SELECT * FROM deployments WHERE repository_id = ? AND is_current = 1 LIMIT 1;",
            (repo_id,),
        ) as cur:
            row = await cur.fetchone()
            return row_to_dict(row, DEPLOYMENT_BOOL_FIELDS)


async def find_active_deployment(
    identifier: str,
    conn: Optional[aiosqlite.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve an active deployment by repo ID, repo name, deployment ID, or container name.

    Args:
        identifier: Repository ID/name, deployment ID, or container name.
        conn: Optional active database connection.

    Returns:
        Active deployment dict, or None if no matching active deployment found.
    """
    clean_id = identifier.strip().rstrip("/")
    if not clean_id:
        return None

    async with _get_conn(conn) as c:
        # 1. Direct match on current deployment by repository_id
        async with c.execute(
            "SELECT * FROM deployments WHERE repository_id = ? AND is_current = 1 LIMIT 1;",
            (clean_id,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return row_to_dict(row, DEPLOYMENT_BOOL_FIELDS)

        # 2. Match repository by ID prefix or name
        async with c.execute(
            "SELECT id FROM repositories WHERE id = ? OR name = ? OR id LIKE ? LIMIT 1;",
            (clean_id, clean_id, f"{clean_id}%"),
        ) as cur:
            r_row = await cur.fetchone()
            if r_row:
                matched_repo_id = r_row["id"]
                async with c.execute(
                    "SELECT * FROM deployments WHERE repository_id = ? AND is_current = 1 LIMIT 1;",
                    (matched_repo_id,),
                ) as dep_cur:
                    d_row = await dep_cur.fetchone()
                    if d_row:
                        return row_to_dict(d_row, DEPLOYMENT_BOOL_FIELDS)

        # 3. Match deployment directly by ID or container_name
        async with c.execute(
            "SELECT * FROM deployments WHERE id = ? OR container_name = ? LIMIT 1;",
            (clean_id, clean_id),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return row_to_dict(row, DEPLOYMENT_BOOL_FIELDS)

        # 4. Fallback: Any running deployment for this repository or matching prefix
        async with c.execute(
            """
            SELECT * FROM deployments
            WHERE (repository_id = ? OR repository_id LIKE ?) AND status = 'running'
            ORDER BY is_current DESC, created_at DESC LIMIT 1;
            """,
            (clean_id, f"{clean_id}%"),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return row_to_dict(row, DEPLOYMENT_BOOL_FIELDS)

    return None
