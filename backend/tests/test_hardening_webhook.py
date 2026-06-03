"""Hardening tests: Clerk svix-verified webhook for user.deleted (BS-03).

`svix` is an optional dependency; when it is not installed the handler verifies
the signature defensively in-process using svix's HMAC-SHA256 scheme. These
tests exercise that path (signature accept/reject, event-type routing, and the
unconfigured-secret refusal) without a real database — the deletion sync call
is patched so we assert routing/verification, not ORM behavior (covered in
test_hardening_repository.py).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


_SECRET_KEY_BYTES = b"0123456789abcdef0123456789abcdef"
_SECRET = "whsec_" + base64.b64encode(_SECRET_KEY_BYTES).decode()


def _reload_main_with_env(**env: str):
    for k in ("APP_ENV", "REQUIRE_CLERK_AUTH", "CLERK_WEBHOOK_SECRET"):
        os.environ.pop(k, None)
    os.environ.update(env)
    for mod in ("main", "auth"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
        else:
            importlib.import_module(mod)
    return sys.modules["main"]


def _sign(body: bytes, svix_id="msg_1", ts="1700000000"):
    signed = f"{svix_id}.{ts}.".encode() + body
    sig = base64.b64encode(
        hmac.new(_SECRET_KEY_BYTES, signed, hashlib.sha256).digest()
    ).decode()
    return {
        "svix-id": svix_id,
        "svix-timestamp": ts,
        "svix-signature": f"v1,{sig}",
    }


class SvixSignatureTests(unittest.TestCase):
    """Unit-level: the in-process HMAC verifier accepts good, rejects bad."""

    def setUp(self):
        self.main = _reload_main_with_env(APP_ENV="test")

    def test_valid_signature_accepts(self):
        body = b'{"type":"user.deleted","data":{"id":"u1"}}'
        headers = _sign(body)
        self.assertTrue(self.main._verify_svix_signature(_SECRET, headers, body))

    def test_tampered_body_rejected(self):
        body = b'{"type":"user.deleted","data":{"id":"u1"}}'
        headers = _sign(body)
        tampered = b'{"type":"user.deleted","data":{"id":"victim"}}'
        self.assertFalse(self.main._verify_svix_signature(_SECRET, headers, tampered))

    def test_missing_headers_rejected(self):
        body = b"{}"
        self.assertFalse(self.main._verify_svix_signature(_SECRET, {}, body))

    def test_wrong_secret_rejected(self):
        body = b'{"type":"user.deleted","data":{"id":"u1"}}'
        headers = _sign(body)
        other = "whsec_" + base64.b64encode(b"x" * 32).decode()
        self.assertFalse(self.main._verify_svix_signature(other, headers, body))


class ClerkWebhookEndpointTests(unittest.TestCase):
    def _client(self, **env):
        from fastapi.testclient import TestClient

        m = _reload_main_with_env(**env)
        return m, TestClient(m.app)

    def test_unconfigured_secret_refuses(self):
        _m, client = self._client(APP_ENV="test")  # no CLERK_WEBHOOK_SECRET
        r = client.post("/webhooks/clerk", content=b"{}")
        self.assertEqual(r.status_code, 503)

    def test_bad_signature_returns_401(self):
        _m, client = self._client(APP_ENV="test", CLERK_WEBHOOK_SECRET=_SECRET)
        body = b'{"type":"user.deleted","data":{"id":"u1"}}'
        r = client.post(
            "/webhooks/clerk",
            content=body,
            headers={"svix-id": "x", "svix-timestamp": "1", "svix-signature": "v1,bad"},
        )
        self.assertEqual(r.status_code, 401)

    def test_user_deleted_triggers_delete(self):
        m, client = self._client(APP_ENV="test", CLERK_WEBHOOK_SECRET=_SECRET)
        body = json.dumps({"type": "user.deleted", "data": {"id": "clerk_42"}}).encode()
        with mock.patch.object(m, "_delete_clerk_user_sync", return_value=True) as del_mock:
            r = client.post("/webhooks/clerk", content=body, headers=_sign(body))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok", "deleted": True})
        del_mock.assert_called_once_with("clerk_42")

    def test_other_event_is_ignored_no_delete(self):
        m, client = self._client(APP_ENV="test", CLERK_WEBHOOK_SECRET=_SECRET)
        body = json.dumps({"type": "user.created", "data": {"id": "clerk_99"}}).encode()
        with mock.patch.object(m, "_delete_clerk_user_sync") as del_mock:
            r = client.post("/webhooks/clerk", content=body, headers=_sign(body))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "ignored")
        del_mock.assert_not_called()

    def test_user_deleted_missing_id_rejected(self):
        m, client = self._client(APP_ENV="test", CLERK_WEBHOOK_SECRET=_SECRET)
        body = json.dumps({"type": "user.deleted", "data": {}}).encode()
        with mock.patch.object(m, "_delete_clerk_user_sync") as del_mock:
            r = client.post("/webhooks/clerk", content=body, headers=_sign(body))
        self.assertEqual(r.status_code, 400)
        del_mock.assert_not_called()

    @classmethod
    def tearDownClass(cls):
        # Restore a clean local main for any later test in the same process.
        _reload_main_with_env(APP_ENV="test")


if __name__ == "__main__":
    unittest.main()
