"""Hardening tests: X-Forwarded-For trusted-proxy hop selection (security-3).

_trusted_forwarded_ip must pick the client IP based on the configured number
of trusted reverse-proxy hops, never blindly trusting forgeable leftmost
client-supplied entries (which would let an attacker rotate rate-limit
buckets). With hops=0 (app directly internet-facing) XFF is fully untrusted.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main  # noqa: E402


class TrustedForwardedIpTests(unittest.TestCase):
    def test_single_proxy_picks_rightmost(self):
        with mock.patch.object(main, "_TRUSTED_PROXY_HOPS", 1):
            # "client, edge" — edge (rightmost) was appended by our proxy.
            self.assertEqual(
                main._trusted_forwarded_ip("1.1.1.1, 9.9.9.9"), "9.9.9.9"
            )

    def test_spoofed_leftmost_is_ignored(self):
        # Attacker supplies a forged leftmost hop hoping to rotate buckets.
        with mock.patch.object(main, "_TRUSTED_PROXY_HOPS", 1):
            picked = main._trusted_forwarded_ip("evil-spoof, 203.0.113.7")
            self.assertEqual(picked, "203.0.113.7")

    def test_two_trusted_hops_picks_second_from_right(self):
        with mock.patch.object(main, "_TRUSTED_PROXY_HOPS", 2):
            # hops=N selects parts[-N]: with 2 trusted hops the chosen entry is
            # the second-from-right (the hop our outer proxy recorded as its
            # upstream), never a forgeable leftmost client-supplied value.
            self.assertEqual(
                main._trusted_forwarded_ip("5.5.5.5, 6.6.6.6, 7.7.7.7"), "6.6.6.6"
            )

    def test_zero_hops_means_xff_untrusted(self):
        with mock.patch.object(main, "_TRUSTED_PROXY_HOPS", 0):
            self.assertIsNone(main._trusted_forwarded_ip("1.2.3.4, 5.6.7.8"))

    def test_empty_header_returns_none(self):
        with mock.patch.object(main, "_TRUSTED_PROXY_HOPS", 1):
            self.assertIsNone(main._trusted_forwarded_ip(""))
            self.assertIsNone(main._trusted_forwarded_ip("   "))

    def test_chain_shorter_than_hops_falls_back_to_leftmost(self):
        # Declared 2 trusted hops but only 1 entry present: do not index OOB.
        with mock.patch.object(main, "_TRUSTED_PROXY_HOPS", 2):
            self.assertEqual(main._trusted_forwarded_ip("8.8.8.8"), "8.8.8.8")

    def test_single_entry_single_hop(self):
        with mock.patch.object(main, "_TRUSTED_PROXY_HOPS", 1):
            self.assertEqual(main._trusted_forwarded_ip("4.4.4.4"), "4.4.4.4")


if __name__ == "__main__":
    unittest.main()
