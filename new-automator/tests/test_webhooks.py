"""Automated tests for GitHub webhook signature verification and payload processing."""

import hashlib
import hmac
import json
import unittest

from git_integration.webhook import (
    parse_pull_request_event,
    parse_push_event,
    parse_webhook_event,
    verify_webhook_signature,
)


class TestWebhookProcessing(unittest.TestCase):
    """Test webhook signature verification and push/PR payload extraction."""

    def setUp(self):
        self.secret = "my_top_secret_webhook_key_12345"

    def _compute_sig(self, body_str: str) -> str:
        digest = hmac.new(
            self.secret.encode("utf-8"),
            body_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={digest}"

    def test_valid_signature_verification(self):
        payload = '{"ref": "refs/heads/main"}'
        sig = self._compute_sig(payload)
        self.assertTrue(verify_webhook_signature(payload, sig, self.secret))

    def test_invalid_signature_rejected(self):
        payload = '{"ref": "refs/heads/main"}'
        bad_sig = "sha256=0000000000000000000000000000000000000000000000000000000000000000"
        self.assertFalse(verify_webhook_signature(payload, bad_sig, self.secret))

    def test_missing_or_malformed_signature_header(self):
        payload = '{"ref": "refs/heads/main"}'
        self.assertFalse(verify_webhook_signature(payload, "", self.secret))
        self.assertFalse(verify_webhook_signature(payload, "invalid_prefix", self.secret))

    def test_parse_valid_push_event(self):
        payload = {
            "ref": "refs/heads/feature/login",
            "after": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
            "repository": {
                "name": "cool-project",
                "full_name": "octocat/cool-project",
                "clone_url": "https://github.com/octocat/cool-project.git",
            },
            "head_commit": {
                "id": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
                "message": "Add OAuth login provider",
                "author": {"name": "Alice Developer", "username": "alice"},
            },
        }

        event = parse_push_event(payload, delivery_id="deliv-001")
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "push")
        self.assertEqual(event.branch, "feature/login")
        self.assertEqual(event.commit_sha, "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b")
        self.assertEqual(event.commit_message, "Add OAuth login provider")
        self.assertEqual(event.author, "alice")
        self.assertEqual(event.repo_url, "https://github.com/octocat/cool-project.git")

    def test_ignore_branch_deletion_push(self):
        payload = {
            "ref": "refs/heads/deleted-branch",
            "deleted": True,
            "after": "0000000000000000000000000000000000000000",
        }
        event = parse_push_event(payload, delivery_id="deliv-del")
        self.assertIsNone(event)

    def test_ignore_tag_push(self):
        payload = {
            "ref": "refs/tags/v1.0.0",
            "after": "abcdef1234567890",
        }
        event = parse_push_event(payload, delivery_id="deliv-tag")
        self.assertIsNone(event)

    def test_parse_pull_request_event(self):
        payload = {
            "action": "opened",
            "number": 42,
            "pull_request": {
                "number": 42,
                "title": "Upgrade dependency versions",
                "user": {"login": "bob"},
                "head": {
                    "ref": "fix/deps",
                    "sha": "9f8e7d6c5b4a3a2b1c0d",
                },
                "base": {
                    "ref": "main",
                },
            },
            "repository": {
                "full_name": "octocat/cool-project",
                "clone_url": "https://github.com/octocat/cool-project.git",
            },
        }

        event = parse_pull_request_event(payload, delivery_id="deliv-pr-01")
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "pull_request")
        self.assertEqual(event.action, "opened")
        self.assertEqual(event.pr_number, 42)
        self.assertEqual(event.commit_sha, "9f8e7d6c5b4a3a2b1c0d")
        self.assertEqual(event.branch, "fix/deps")
        self.assertEqual(event.pr_base_branch, "main")

    def test_unsupported_pr_action_ignored(self):
        payload = {
            "action": "labeled",
            "number": 42,
            "pull_request": {},
        }
        event = parse_pull_request_event(payload, delivery_id="deliv-pr-lbl")
        self.assertIsNone(event)

    def test_router_unsupported_event_type(self):
        event = parse_webhook_event("issues", {"action": "created"}, delivery_id="deliv-issue")
        self.assertIsNone(event)


if __name__ == "__main__":
    unittest.main()
