"""
Git repository URL and ref validation module.

Provides validation and parsing for Git URLs, branch names, commit SHAs,
and sanitization for filesystem and container names.
"""

from dataclasses import dataclass
import re
from urllib.parse import urlparse


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass(frozen=True)
class ParsedGitUrl:
    """Parsed components of a Git repository URL."""

    provider: str      # e.g., 'github.com'
    owner: str         # e.g., 'user'
    repo_name: str     # e.g., 'project'
    original_url: str  # the input URL
    clone_url: str     # normalized HTTPS clone URL


# Windows reserved device names that cannot be used as folder names
_WINDOWS_RESERVED_NAMES = frozenset({
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
})


# ============================================================
# GIT URL VALIDATION
# ============================================================

def validate_git_url(url: str, allowed_providers: list[str] | None = None) -> ParsedGitUrl:
    """Validate and parse a Git repository URL.

    Supports HTTPS URLs like:
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - github.com/owner/repo

    Args:
        url: The Git repository URL to validate.
        allowed_providers: Optional list of allowed provider hostnames
            (e.g., ['github.com', 'gitlab.com']).

    Returns:
        ParsedGitUrl: Parsed and normalized repository information.

    Raises:
        ValueError: If the URL is empty, malformed, unsupported, or from a disallowed provider.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError("Git repository URL cannot be empty.")

    clean_url = url.strip()

    # Reject SSH protocol formats explicitly with helpful message
    if clean_url.startswith("git@") or clean_url.startswith("ssh://"):
        raise ValueError("SSH Git URLs are not supported. Please provide an HTTPS URL.")

    # Prepend https:// if no scheme is provided
    if "://" not in clean_url:
        clean_url = f"https://{clean_url}"

    parsed = urlparse(clean_url)

    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(
            f"Unsupported URL scheme '{parsed.scheme}'. Only HTTPS (or HTTP) URLs are supported."
        )

    if not parsed.hostname:
        raise ValueError(f"Could not parse hostname from Git URL: '{url}'")

    provider = parsed.hostname.lower()
    port_str = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
    provider_with_port = f"{provider}{port_str}"

    # Validate provider against allowed providers list if provided
    if allowed_providers is not None:
        allowed_lower = [p.lower() for p in allowed_providers]
        if provider not in allowed_lower and provider_with_port not in allowed_lower:
            raise ValueError(
                f"Provider '{provider}' is not in allowed providers: {allowed_providers}"
            )

    # Extract owner and repo name from path
    path_segments = [seg for seg in parsed.path.strip("/").split("/") if seg]
    if len(path_segments) < 2:
        raise ValueError(
            f"Invalid repository path '{parsed.path}'. Expected 'owner/repo' format."
        )

    if len(path_segments) == 2:
        owner = path_segments[0]
        repo_name = path_segments[1]
    else:
        # Handles nested groups e.g. GitLab group/subgroup/repo
        owner = "/".join(path_segments[:-1])
        repo_name = path_segments[-1]

    # Remove .git suffix from repository name
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    if not owner or not repo_name:
        raise ValueError("Repository owner and name must not be empty.")

    # Validate that owner and repo_name contain safe path characters
    for segment in (*owner.split("/"), repo_name):
        if not re.fullmatch(r"^[a-zA-Z0-9_\-\.]+$", segment) or segment in (".", ".."):
            raise ValueError(
                f"Repository owner or name contains invalid characters: '{owner}/{repo_name}'"
            )

    clone_url = f"https://{provider}{port_str}/{owner}/{repo_name}.git"

    return ParsedGitUrl(
        provider=provider,
        owner=owner,
        repo_name=repo_name,
        original_url=url,
        clone_url=clone_url,
    )


# ============================================================
# REF VALIDATION
# ============================================================

def validate_branch_name(branch: str) -> str:
    """Validate a Git branch name.

    Rejects dangerous patterns like '..' and names starting with '-'.

    Args:
        branch: The branch name to validate.

    Returns:
        str: The trimmed, validated branch name.

    Raises:
        ValueError: If the branch name is invalid or contains dangerous characters.
    """
    if not branch or not isinstance(branch, str) or not branch.strip():
        raise ValueError("Branch name cannot be empty.")

    branch = branch.strip()

    # Reject names starting with '-' (command option injection risk)
    if branch.startswith("-"):
        raise ValueError(f"Branch name '{branch}' cannot start with '-' (option injection hazard).")

    # Reject path traversal patterns
    if ".." in branch:
        raise ValueError(f"Branch name '{branch}' cannot contain '..'.")

    # Reject leading or trailing slashes
    if branch.startswith("/") or branch.endswith("/"):
        raise ValueError(f"Branch name '{branch}' cannot start or end with '/'.")

    # Reject consecutive slashes
    if "//" in branch:
        raise ValueError(f"Branch name '{branch}' cannot contain consecutive slashes '//'.")

    # Reject .lock suffix (used by git locks)
    if branch.endswith(".lock"):
        raise ValueError(f"Branch name '{branch}' cannot end with '.lock'.")

    # Reject trailing dot
    if branch.endswith("."):
        raise ValueError(f"Branch name '{branch}' cannot end with a dot '.'.")

    # Reject reflog syntax '@{' or single '@'
    if "@{" in branch or branch == "@":
        raise ValueError(f"Branch name '{branch}' cannot contain reflog syntax '@{{' or be '@'.")

    # Check for illegal git ref characters
    if re.search(r"[\s~^:?*\[\\\"'\x00-\x1f\x7f]", branch):
        raise ValueError(f"Branch name '{branch}' contains illegal characters.")

    return branch


def validate_commit_sha(sha: str) -> str:
    """Validate a Git commit SHA (full or abbreviated).

    Args:
        sha: The commit SHA string to validate.

    Returns:
        str: Lowercased, validated commit SHA.

    Raises:
        ValueError: If the SHA is not a valid 4-64 character hexadecimal string.
    """
    if not sha or not isinstance(sha, str) or not sha.strip():
        raise ValueError("Commit SHA cannot be empty.")

    clean_sha = sha.strip().lower()

    if not re.fullmatch(r"^[0-9a-f]{4,64}$", clean_sha):
        raise ValueError(
            f"Invalid commit SHA: '{sha}'. Expected 4 to 64 hexadecimal characters."
        )

    return clean_sha


# ============================================================
# SANITIZATION
# ============================================================

def sanitize_repo_name(name: str) -> str:
    """Create a filesystem/Docker-safe name from a repo name.

    Transforms the repository name so it can be safely used as a directory name,
    Docker image/tag component, or container identifier.

    Args:
        name: The raw repository or project name.

    Returns:
        str: A sanitized, lowercase, alphanumeric identifier safe for Docker and filesystems.
    """
    if not name or not isinstance(name, str) or not name.strip():
        return "repo"

    sanitized = name.strip().lower()
    # Replace non-alphanumeric, non-hyphen, non-underscore chars with hyphens
    sanitized = re.sub(r"[^a-z0-9_-]+", "-", sanitized)
    # Collapse multiple consecutive hyphens
    sanitized = re.sub(r"[-_]+", "-", sanitized)
    # Strip leading/trailing punctuation
    sanitized = sanitized.strip(".-_")

    if not sanitized:
        return "repo"

    # Avoid Windows reserved device names
    if sanitized in _WINDOWS_RESERVED_NAMES:
        return f"repo-{sanitized}"

    return sanitized
