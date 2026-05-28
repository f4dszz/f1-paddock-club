"""Auth helper tests with monkey-patched JWKS to avoid network access."""
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
        self.kid = "test-kid"

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


class VerifyClerkJwtTests(unittest.TestCase):
    def setUp(self):
        self.keys = _Keys()
        auth.reset_jwks_cache_for_tests()
        patcher = mock.patch.object(auth, "_fetch_jwks", return_value=self.keys.jwks())
        self.addCleanup(patcher.stop)
        patcher.start()
        # Make sure env doesn't leak production into the tests.
        for key in ("APP_ENV", "REQUIRE_CLERK_AUTH"):
            os.environ.pop(key, None)
        os.environ["CLERK_JWT_ISSUER"] = _ISSUER

    def tearDown(self):
        os.environ.pop("CLERK_JWT_ISSUER", None)
        os.environ.pop("DEMO_ACCESS_TOKEN", None)

    def test_valid_token_returns_sub(self):
        token = self.keys.make({
            "iss": _ISSUER,
            "sub": "user_abc",
            "exp": int(time.time()) + 60,
        })
        claims = auth.verify_clerk_jwt(token, issuer=_ISSUER)
        self.assertEqual(claims["sub"], "user_abc")

    def test_expired_rejected(self):
        token = self.keys.make({
            "iss": _ISSUER,
            "sub": "user_abc",
            "exp": int(time.time()) - 1,
        })
        with self.assertRaises(auth.AuthError):
            auth.verify_clerk_jwt(token, issuer=_ISSUER)

    def test_wrong_issuer_rejected(self):
        token = self.keys.make({
            "iss": "https://evil.example",
            "sub": "x",
            "exp": int(time.time()) + 60,
        })
        with self.assertRaises(auth.AuthError):
            auth.verify_clerk_jwt(token, issuer=_ISSUER)

    def test_bad_signature_rejected(self):
        other = _Keys()
        token = other.make({
            "iss": _ISSUER,
            "sub": "x",
            "exp": int(time.time()) + 60,
        })
        with self.assertRaises(auth.AuthError):
            auth.verify_clerk_jwt(token, issuer=_ISSUER)

    def test_malformed_rejected(self):
        with self.assertRaises(auth.AuthError):
            auth.verify_clerk_jwt("not.a.token", issuer=_ISSUER)

    def test_missing_kid_rejected(self):
        token = jwt.encode(
            {"iss": _ISSUER, "sub": "x", "exp": int(time.time()) + 60},
            self.keys.priv,
            algorithm="RS256",
            # explicitly no kid header
        )
        with self.assertRaises(auth.AuthError):
            auth.verify_clerk_jwt(token, issuer=_ISSUER)


class RequireUserDependencyTests(unittest.TestCase):
    def setUp(self):
        self.keys = _Keys()
        auth.reset_jwks_cache_for_tests()
        for key in ("APP_ENV", "REQUIRE_CLERK_AUTH", "DEMO_ACCESS_TOKEN",
                    "CLERK_JWT_ISSUER", "CLERK_JWKS_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        for key in ("APP_ENV", "REQUIRE_CLERK_AUTH", "DEMO_ACCESS_TOKEN",
                    "CLERK_JWT_ISSUER", "CLERK_JWKS_URL"):
            os.environ.pop(key, None)

    def test_no_auth_configured_returns_demo_user(self):
        # Pure local dev, no DEMO_ACCESS_TOKEN, no CLERK → accept-all
        self.assertEqual(auth.require_user(authorization=None), "demo-user")

    def test_demo_token_valid_returns_demo_user(self):
        os.environ["DEMO_ACCESS_TOKEN"] = "demo-123"
        self.assertEqual(auth.require_user(authorization="Bearer demo-123"), "demo-user")

    def test_demo_token_missing_when_required_raises(self):
        os.environ["DEMO_ACCESS_TOKEN"] = "demo-123"
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            auth.require_user(authorization=None)
        self.assertEqual(cm.exception.status_code, 401)

    def test_demo_token_wrong_raises(self):
        os.environ["DEMO_ACCESS_TOKEN"] = "demo-123"
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            auth.require_user(authorization="Bearer wrong")
        self.assertEqual(cm.exception.status_code, 401)

    def test_clerk_valid_in_prod_returns_sub(self):
        os.environ["APP_ENV"] = "production"
        os.environ["CLERK_JWT_ISSUER"] = _ISSUER
        with mock.patch.object(auth, "_fetch_jwks", return_value=self.keys.jwks()):
            tok = self.keys.make({
                "iss": _ISSUER, "sub": "user_prod", "exp": int(time.time()) + 60,
            })
            self.assertEqual(auth.require_user(authorization=f"Bearer {tok}"), "user_prod")

    def test_clerk_invalid_in_prod_raises_401(self):
        os.environ["APP_ENV"] = "production"
        os.environ["CLERK_JWT_ISSUER"] = _ISSUER
        from fastapi import HTTPException
        with mock.patch.object(auth, "_fetch_jwks", return_value=self.keys.jwks()):
            with self.assertRaises(HTTPException) as cm:
                auth.require_user(authorization="Bearer not-a-token")
            self.assertEqual(cm.exception.status_code, 401)

    def test_prod_without_clerk_configured_raises_503(self):
        os.environ["APP_ENV"] = "production"
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            auth.require_user(authorization=None)
        self.assertEqual(cm.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
