"""
GitHub webhook signature verification and payload parsing module.

Supports push and pull_request webhook events with HMAC-SHA256 signature
verification, payload routing, and structured event extraction.
"""

from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass(frozen=True)
class WebhookEvent:
    """Parsed and validated GitHub webhook event."""

    delivery_id: str
    event_type: str       # 'push' or 'pull_request'
    action: str | None    # PR action: 'opened', 'synchronize', 'reopened', etc.
    repo_url: str         # repository clone URL
    repo_full_name: str   # 'owner/repo'
    branch: str           # affected branch
    commit_sha: str       # exact commit SHA
    commit_message: str
    author: str
    pr_number: int | None
    pr_title: str | None
    pr_head_sha: str | None
    pr_base_branch: str | None


# ============================================================
# SIGNATURE VERIFICATION
# ============================================================

def verify_webhook_signature(
    payload_body: bytes | str,
    signature_header: str,
    secret: str,
) -> bool:
    """Verify GitHub HMAC-SHA256 webhook signature using constant-time comparison.

    Args:
        payload_body: Raw request body as bytes or string.
        signature_header: X-Hub-Signature-256 header value (e.g., 'sha256=<hex>').
        secret: Configured webhook secret.

    Returns:
        bool: True if signature is valid, False otherwise.
    """
    if not payload_body or not signature_header or not secret:
        logger.warning("Webhook verification failed: missing body, signature header, or secret.")
        return False

    if isinstance(payload_body, str):
        body_bytes = payload_body.encode("utf-8")
    else:
        body_bytes = payload_body

    sig = signature_header.strip()
    if not sig.startswith("sha256="):
        logger.warning("Webhook signature header missing 'sha256=' prefix.")
        return False

    received_digest = sig[len("sha256="):].strip()
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret

    expected_digest = hmac.new(
        secret_bytes,
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_digest, received_digest)


# ============================================================
# PAYLOAD PARSING
# ============================================================

def parse_push_event(payload: dict[str, Any], delivery_id: str) -> WebhookEvent | None:
    """Parse a GitHub push event payload.

    Extracts branch from ref (refs/heads/<branch>).
    Extracts head commit SHA and message.
    Ignores tag pushes and branch deletions.

    Args:
        payload: Decoded JSON dictionary of the push webhook.
        delivery_id: GitHub delivery ID from X-GitHub-Delivery header.

    Returns:
        WebhookEvent | None: Parsed event details, or None if the event should be ignored.
    """
    ref = payload.get("ref", "")
    if not ref.startswith("refs/heads/"):
        logger.info("Ignoring push event for non-branch ref: %s", ref)
        return None

    # Ignore branch deletions
    zero_sha = "0000000000000000000000000000000000000000"
    if payload.get("deleted") is True or payload.get("after") == zero_sha:
        logger.info("Ignoring branch deletion push event for %s", ref)
        return None

    branch = ref[len("refs/heads/"):]

    # Extract repository details
    repo_data = payload.get("repository") or {}
    repo_url = repo_data.get("clone_url") or repo_data.get("html_url") or ""
    repo_full_name = repo_data.get("full_name") or ""

    # Extract commit details
    head_commit = payload.get("head_commit") or {}
    commit_sha = payload.get("after") or head_commit.get("id") or ""
    commit_message = head_commit.get("message") or ""

    # Extract author
    author_info = head_commit.get("author") or {}
    author = (
        author_info.get("username")
        or author_info.get("name")
        or (payload.get("pusher") or {}).get("name")
        or (payload.get("sender") or {}).get("login")
        or "unknown"
    )

    return WebhookEvent(
        delivery_id=delivery_id,
        event_type="push",
        action=None,
        repo_url=repo_url,
        repo_full_name=repo_full_name,
        branch=branch,
        commit_sha=commit_sha,
        commit_message=commit_message,
        author=author,
        pr_number=None,
        pr_title=None,
        pr_head_sha=None,
        pr_base_branch=None,
    )


def parse_pull_request_event(payload: dict[str, Any], delivery_id: str) -> WebhookEvent | None:
    """Parse a GitHub pull_request event payload.

    Only processes 'opened', 'synchronize', and 'reopened' actions.
    Extracts PR head SHA, base branch, PR number.

    Args:
        payload: Decoded JSON dictionary of the pull_request webhook.
        delivery_id: GitHub delivery ID from X-GitHub-Delivery header.

    Returns:
        WebhookEvent | None: Parsed event details, or None if action should be ignored.
    """
    action = payload.get("action")
    allowed_actions = ("opened", "synchronize", "reopened")

    if action not in allowed_actions:
        logger.info("Ignoring pull_request event with action '%s'", action)
        return None

    pr = payload.get("pull_request") or {}
    pr_head = pr.get("head") or {}
    pr_base = pr.get("base") or {}

    pr_number = pr.get("number") or payload.get("number")
    pr_title = pr.get("title") or ""
    pr_head_sha = pr_head.get("sha") or ""
    pr_base_branch = pr_base.get("ref") or ""
    branch = pr_head.get("ref") or ""

    repo_data = payload.get("repository") or pr.get("head", {}).get("repo") or {}
    repo_url = repo_data.get("clone_url") or repo_data.get("html_url") or ""
    repo_full_name = repo_data.get("full_name") or ""

    author = (pr.get("user") or {}).get("login") or (payload.get("sender") or {}).get("login") or "unknown"

    return WebhookEvent(
        delivery_id=delivery_id,
        event_type="pull_request",
        action=action,
        repo_url=repo_url,
        repo_full_name=repo_full_name,
        branch=branch,
        commit_sha=pr_head_sha,
        commit_message=pr_title,
        author=author,
        pr_number=pr_number,
        pr_title=pr_title,
        pr_head_sha=pr_head_sha,
        pr_base_branch=pr_base_branch,
    )


def parse_webhook_event(
    event_type: str,
    payload: dict[str, Any] | str | bytes,
    delivery_id: str,
) -> WebhookEvent | None:
    """Route to the appropriate parser based on event type.

    Args:
        event_type: Event type name from X-GitHub-Event header ('push', 'pull_request').
        payload: Webhook JSON dictionary or raw JSON string/bytes.
        delivery_id: GitHub delivery ID from X-GitHub-Delivery header.

    Returns:
        WebhookEvent | None: Structured webhook event or None if unsupported or ignored.
    """
    if isinstance(payload, (str, bytes)):
        try:
            payload_dict = json.loads(payload)
        except json.JSONDecodeError as exc:
            logger.error("Failed to decode webhook payload JSON: %s", exc)
            return None
    elif isinstance(payload, dict):
        payload_dict = payload
    else:
        logger.error("Invalid payload type for webhook: %s", type(payload))
        return None

    clean_event = event_type.strip().lower()

    if clean_event == "push":
        return parse_push_event(payload_dict, delivery_id)
    elif clean_event == "pull_request":
        return parse_pull_request_event(payload_dict, delivery_id)
    else:
        logger.info("Unsupported or unhandled webhook event type: %s", event_type)
        return None
