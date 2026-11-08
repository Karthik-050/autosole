"""
Automator Git Integration Module.

Provides Git repository management, URL/ref validation, workspace isolation,
and GitHub webhook processing for CI/CD automation pipelines.
"""

from .repository import (
    CloneResult,
    CommitInfo,
    GitAuthenticationError,
    GitBranchNotFoundError,
    GitCommitNotFoundError,
    GitError,
    GitNetworkError,
    GitRepository,
)
from .validators import (
    ParsedGitUrl,
    sanitize_repo_name,
    validate_branch_name,
    validate_commit_sha,
    validate_git_url,
)
from .webhook import (
    WebhookEvent,
    parse_pull_request_event,
    parse_push_event,
    parse_webhook_event,
    verify_webhook_signature,
)

__all__ = [
    # Validators
    "ParsedGitUrl",
    "validate_git_url",
    "validate_branch_name",
    "validate_commit_sha",
    "sanitize_repo_name",
    # Repository
    "CommitInfo",
    "CloneResult",
    "GitRepository",
    "GitError",
    "GitAuthenticationError",
    "GitNetworkError",
    "GitBranchNotFoundError",
    "GitCommitNotFoundError",
    # Webhooks
    "WebhookEvent",
    "verify_webhook_signature",
    "parse_push_event",
    "parse_pull_request_event",
    "parse_webhook_event",
]
