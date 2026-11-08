"""Tests for relaying a GitHub delivery to the Collaborative Workspace."""

import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from starlette.requests import Request

from server import app, forward_workspace_github_webhook


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, *, content, headers):
        self.request = {"url": url, "content": content, "headers": headers}
        return self.response


def make_request(body, headers):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/webhooks/github",
        "raw_path": b"/api/webhooks/github",
        "query_string": b"",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "server": ("localhost", 8001),
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope, receive)


class TestWorkspaceWebhookRelay(unittest.IsolatedAsyncioTestCase):
    async def test_forwards_raw_signed_delivery_and_returns_workspace_response(self):
        body = b'{"ref":"refs/heads/main"}'
        workspace_response = httpx.Response(
            202,
            content=b'{"accepted":true}',
            headers={"content-type": "application/json"},
        )
        relay = FakeAsyncClient(workspace_response)
        request = make_request(
            body,
            {
                "content-type": "application/json",
                "x-github-delivery": "delivery-123",
                "x-github-event": "push",
                "x-hub-signature-256": "sha256=signature",
            },
        )

        with patch("server.httpx.AsyncClient", return_value=relay):
            response = await forward_workspace_github_webhook(request)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.body, b'{"accepted":true}')
        self.assertEqual(
            relay.request,
            {
                "url": "http://127.0.0.1:8000/api/webhooks/github",
                "content": body,
                "headers": {
                    "content-type": "application/json",
                    "x-github-delivery": "delivery-123",
                    "x-github-event": "push",
                    "x-hub-signature-256": "sha256=signature",
                },
            },
        )
        self.assertTrue(
            any(
                getattr(route, "path", None) == "/api/webhooks/github"
                and getattr(route, "endpoint", None) is forward_workspace_github_webhook
                for route in app.routes
            )
        )

    async def test_rejects_unsigned_delivery(self):
        request = make_request(b"{}", {"x-github-event": "push"})
        with self.assertRaises(HTTPException) as error:
            await forward_workspace_github_webhook(request)
        self.assertEqual(error.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
