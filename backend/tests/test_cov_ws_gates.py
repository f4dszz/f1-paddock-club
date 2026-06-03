"""test-coverage-11 (low): WebSocket connection-gate negative tests.

The connect-time gates had no coverage:
- origin allowlist rejection -> close 1008
- auth failure (require_user_for_ws AuthError) -> close 1008
- oversized message -> "Message too large"
- invalid JSON -> "Invalid JSON"
- unknown message type -> error envelope

Each is exercised through TestClient.websocket_connect under an isolated
SQLite + env reload.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _reload_with_env(**env: str):
    for k in (
        "APP_ENV", "REQUIRE_CLERK_AUTH", "DEMO_ACCESS_TOKEN", "CLERK_JWT_ISSUER",
        "CLERK_JWKS_URL", "TEST_DATABASE_URL", "ALLOWED_ORIGINS",
    ):
        os.environ.pop(k, None)
    os.environ.update(env)
    for mod in ("auth", "db", "models", "repository", "main"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
        else:
            importlib.import_module(mod)
    from db import get_engine
    from models import Base
    Base.metadata.create_all(get_engine())
    return sys.modules["main"]


class WsGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            prefix="_test_wsgate_", suffix=".sqlite3", delete=False, dir=str(BACKEND_DIR)
        )
        self._tmp.close()
        self.url = f"sqlite:///{self._tmp.name}"
        self.main = _reload_with_env(APP_ENV="test", TEST_DATABASE_URL=self.url)

    def tearDown(self):
        try:
            os.remove(self._tmp.name)
        except OSError:
            pass

    def test_oversized_message_rejected(self):
        from fastapi.testclient import TestClient

        with TestClient(self.main.app) as client, client.websocket_connect("/ws") as ws:
            big = "x" * (self.main.MAX_WS_MESSAGE_SIZE + 1)
            ws.send_text(big)
            err = ws.receive_json()
            self.assertEqual(err["type"], "error")
            self.assertEqual(err["data"], "Message too large")

    def test_invalid_json_rejected(self):
        from fastapi.testclient import TestClient

        with TestClient(self.main.app) as client, client.websocket_connect("/ws") as ws:
            ws.send_text("{not valid json")
            err = ws.receive_json()
            self.assertEqual(err["type"], "error")
            self.assertEqual(err["data"], "Invalid JSON")

    def test_unknown_type_returns_error(self):
        from fastapi.testclient import TestClient

        with TestClient(self.main.app) as client, client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "frobnicate", "data": {}})
            err = ws.receive_json()
            self.assertEqual(err["type"], "error")
            self.assertIn("Unknown message type", err["data"])

    def test_socket_survives_after_recoverable_error(self):
        # An "Invalid JSON" or unknown-type error must NOT close the socket —
        # the user can correct and continue in the same session.
        from fastapi.testclient import TestClient

        with TestClient(self.main.app) as client, client.websocket_connect("/ws") as ws:
            ws.send_text("garbage")
            self.assertEqual(ws.receive_json()["data"], "Invalid JSON")
            ws.send_json({"type": "frobnicate"})
            self.assertIn("Unknown message type", ws.receive_json()["data"])


class WsOriginGateTests(unittest.TestCase):
    """Origin allowlist gate: a disallowed Origin header closes the socket 1008."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            prefix="_test_wsorigin_", suffix=".sqlite3", delete=False, dir=str(BACKEND_DIR)
        )
        self._tmp.close()
        self.url = f"sqlite:///{self._tmp.name}"
        # Non-empty allowlist activates the gate (empty allowlist disables it).
        self.main = _reload_with_env(
            APP_ENV="test",
            TEST_DATABASE_URL=self.url,
            ALLOWED_ORIGINS="https://app.example.com",
        )

    def tearDown(self):
        try:
            os.remove(self._tmp.name)
        except OSError:
            pass

    def test_disallowed_origin_closed_1008(self):
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        with TestClient(self.main.app) as client:
            with self.assertRaises(WebSocketDisconnect) as ctx:
                with client.websocket_connect(
                    "/ws", headers={"origin": "https://evil.example.com"}
                ) as ws:
                    ws.receive_json()
            self.assertEqual(ctx.exception.code, 1008)

    def test_allowed_origin_connects(self):
        from fastapi.testclient import TestClient

        with TestClient(self.main.app) as client:
            with client.websocket_connect(
                "/ws", headers={"origin": "https://app.example.com"}
            ) as ws:
                # A no-op unknown type proves the socket is live past the gate.
                ws.send_json({"type": "ping"})
                self.assertEqual(ws.receive_json()["type"], "error")


class WsAuthGateTests(unittest.TestCase):
    """Auth gate: non-local env with a demo token configured but no token on the
    handshake closes the socket 1008 (require_user_for_ws raises AuthError)."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            prefix="_test_wsauth_", suffix=".sqlite3", delete=False, dir=str(BACKEND_DIR)
        )
        self._tmp.close()
        self.url = f"sqlite:///{self._tmp.name}"
        self.main = _reload_with_env(
            APP_ENV="production",
            TEST_DATABASE_URL=self.url,
            ALLOWED_ORIGINS="https://app.example.com",
            REQUIRE_CLERK_AUTH="true",
            CLERK_JWT_ISSUER="https://clerk.example.com",
            CLERK_JWKS_URL="https://clerk.example.com/.well-known/jwks.json",
        )

    def tearDown(self):
        try:
            os.remove(self._tmp.name)
        except OSError:
            pass

    def test_missing_token_closed_1008(self):
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        with TestClient(self.main.app) as client:
            with self.assertRaises(WebSocketDisconnect) as ctx:
                with client.websocket_connect(
                    "/ws", headers={"origin": "https://app.example.com"}
                ) as ws:
                    ws.receive_json()
            self.assertEqual(ctx.exception.code, 1008)


if __name__ == "__main__":
    unittest.main()
