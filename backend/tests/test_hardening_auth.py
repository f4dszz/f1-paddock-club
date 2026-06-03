"""Hardening tests: Clerk JWT audience verification (security-1).

When CLERK_AUDIENCE is set, verify_clerk_jwt must require and check the `aud`
claim so a token minted for a *different* application on the same Clerk
issuer/JWKS is rejected. When CLERK_AUDIENCE is unset, audience is not checked
(local/demo tokens carry no `aud`) and verification keeps working.

JWKS is monkey-patched so no network access occurs.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

import auth  # noqa: E402


_ISSUER = "https://test.clerk.example"


class _Keys:
    def __init__(self):
        self.priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.pub = self.priv.public_key()
        self.kid = "hardening-kid"

    def jwks(self):
        nums = self.pub.public_numbers()
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": self.kid,
                    "alg": "RS256",
                    "use": "sig",
                    "n": jwt.utils.to_base64url_uint(nums.n).decode(),
                    "e": jwt.utils.to_base64url_uint(nums.e).decode(),
                }
            ]
        }

    def make(self, claims):
        return jwt.encode(claims, self.priv, algorithm="RS256", headers={"kid": self.kid})


class ClerkAudienceTests(unittest.TestCase):
    def setUp(self):
        self.keys = _Keys()
        auth.reset_jwks_cache_for_tests()
        patcher = mock.patch.object(auth, "_fetch_jwks", return_value=self.keys.jwks())
        self.addCleanup(patcher.stop)
        patcher.start()
        for key in ("APP_ENV", "REQUIRE_CLERK_AUTH", "CLERK_AUDIENCE"):
            os.environ.pop(key, None)
        os.environ["CLERK_JWT_ISSUER"] = _ISSUER

    def tearDown(self):
        for key in ("CLERK_JWT_ISSUER", "CLERK_AUDIENCE"):
            os.environ.pop(key, None)

    def _claims(self, **extra):
        now = int(time.time())
        base = {"iss": _ISSUER, "sub": "user_123", "exp": now + 3600, "iat": now}
        base.update(extra)
        return base

    def test_audience_unset_accepts_token_without_aud(self):
        # Default/local behavior: no audience configured, token has no aud.
        token = self.keys.make(self._claims())
        claims = auth.verify_clerk_jwt(token)
        self.assertEqual(claims["sub"], "user_123")

    def test_matching_audience_accepted(self):
        os.environ["CLERK_AUDIENCE"] = "my-api"
        token = self.keys.make(self._claims(aud="my-api"))
        claims = auth.verify_clerk_jwt(token)
        self.assertEqual(claims["sub"], "user_123")

    def test_wrong_audience_rejected(self):
        os.environ["CLERK_AUDIENCE"] = "my-api"
        token = self.keys.make(self._claims(aud="some-other-app"))
        with self.assertRaises(auth.AuthError):
            auth.verify_clerk_jwt(token)

    def test_missing_aud_rejected_when_audience_required(self):
        # A token minted with no aud must be rejected once an audience is pinned.
        os.environ["CLERK_AUDIENCE"] = "my-api"
        token = self.keys.make(self._claims())  # no aud claim
        with self.assertRaises(auth.AuthError):
            auth.verify_clerk_jwt(token)

    def test_clerk_audience_reader_strips_whitespace(self):
        os.environ["CLERK_AUDIENCE"] = "  my-api  "
        self.assertEqual(auth._clerk_audience(), "my-api")

    def test_clerk_audience_unset_is_empty(self):
        os.environ.pop("CLERK_AUDIENCE", None)
        self.assertEqual(auth._clerk_audience(), "")


if __name__ == "__main__":
    unittest.main()
