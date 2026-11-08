import hashlib
import hmac
import unittest

from backend.routers.webhooks import normalize_github_remote, verify_github_signature


class TestGitHubWebhookSecurity(unittest.TestCase):
    def test_signature_requires_valid_sha256_hmac(self):
        body = b'{"ref":"refs/heads/main"}'
        secret = "a-long-test-secret"
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        self.assertTrue(verify_github_signature(body, f"sha256={digest}", secret))
        self.assertFalse(verify_github_signature(body, f"sha1={digest}", secret))
        self.assertFalse(verify_github_signature(body, f"sha256={digest}", "wrong-secret"))
        self.assertFalse(verify_github_signature(body, f"sha256={digest}", ""))

    def test_repository_match_normalizes_git_suffix(self):
        self.assertEqual(
            normalize_github_remote("https://github.com/Example/Project.git"),
            normalize_github_remote("https://github.com/example/project"),
        )
        self.assertIsNone(normalize_github_remote("https://evil.example/example/project.git"))


if __name__ == "__main__":
    unittest.main()
