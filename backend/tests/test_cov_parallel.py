"""test-coverage-3: tools/_parallel.py query_parallel + DegradationReport.

The most subtle path — a global FuturesTimeout that must KEEP already-completed
results (instead of crashing the whole search into a full mock fallback) and
mark the unfinished sources as 'timeout' — had zero coverage. Also exercises
success+empty+raising mixes, str-result pass-through, and DegradationReport
properties/summary.
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tools._parallel import (  # noqa: E402
    DegradationReport,
    SourceStatus,
    query_parallel,
)


class DegradationReportTests(unittest.TestCase):
    def test_properties_all_ok(self):
        r = DegradationReport(sources=[
            SourceStatus("a", ok=True, count=3),
            SourceStatus("b", ok=True, count=2),
        ])
        self.assertFalse(r.any_failed)
        self.assertFalse(r.all_failed)
        self.assertEqual(r.succeeded, ["a", "b"])
        self.assertEqual(r.failed, [])
        self.assertEqual(r.summary(), "a(3) | b(2)")

    def test_properties_partial_failure(self):
        r = DegradationReport(sources=[
            SourceStatus("a", ok=True, count=3),
            SourceStatus("b", ok=False, error="timeout"),
        ])
        self.assertTrue(r.any_failed)
        self.assertFalse(r.all_failed)
        self.assertEqual(r.succeeded, ["a"])
        self.assertEqual(r.failed, ["b"])
        self.assertIn("FAILED:b(timeout)", r.summary())

    def test_properties_all_failed(self):
        r = DegradationReport(sources=[
            SourceStatus("a", ok=False, error="401"),
            SourceStatus("b", ok=False, error="timeout"),
        ])
        self.assertTrue(r.any_failed)
        self.assertTrue(r.all_failed)
        self.assertEqual(r.succeeded, [])
        self.assertEqual(r.failed, ["a", "b"])


class QueryParallelTests(unittest.TestCase):
    def test_empty_sources_returns_empty(self):
        results, report = query_parallel({})
        self.assertEqual(results, [])
        self.assertEqual(report.sources, [])
        self.assertFalse(report.any_failed)

    def test_success_empty_and_raising_mix(self):
        def ok():
            return [{"name": "x"}, {"name": "y"}]

        def empty():
            return []

        def boom():
            raise RuntimeError("provider exploded")

        results, report = query_parallel(
            {"good": ok, "blank": empty, "bad": boom}, timeout=10
        )

        # Only the good source contributed results; each tagged with _source.
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r["_source"], "good")
            self.assertFalse(r["_degraded"])

        by_name = {s.name: s for s in report.sources}
        self.assertTrue(by_name["good"].ok)
        self.assertEqual(by_name["good"].count, 2)
        self.assertFalse(by_name["blank"].ok)
        self.assertEqual(by_name["blank"].error, "empty")
        self.assertFalse(by_name["bad"].ok)
        self.assertIn("RuntimeError", by_name["bad"].error)
        self.assertTrue(report.any_failed)

    def test_str_results_pass_through_untagged(self):
        # Ticket sources return list[str] (raw snippets), not dicts.
        def text_source():
            return ["snippet one", "snippet two"]

        results, report = query_parallel({"snips": text_source}, timeout=10)
        self.assertEqual(results, ["snippet one", "snippet two"])
        self.assertTrue(report.sources[0].ok)
        self.assertEqual(report.sources[0].count, 2)

    def test_global_timeout_keeps_completed_and_marks_slow_as_timeout(self):
        # 'fast' returns immediately; 'slow' blocks well past the deadline.
        release = threading.Event()

        def fast():
            return [{"id": 1}]

        def slow():
            # Wait until the test releases it (long after the global timeout).
            release.wait(timeout=5)
            return [{"id": 2}]

        try:
            results, report = query_parallel(
                {"fast": fast, "slow": slow}, timeout=0.3
            )
        finally:
            release.set()  # let the slow worker exit cleanly

        # Completed result is retained, not discarded.
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["_source"], "fast")

        by_name = {s.name: s for s in report.sources}
        self.assertTrue(by_name["fast"].ok)
        self.assertIn("slow", by_name)
        self.assertFalse(by_name["slow"].ok)
        self.assertEqual(by_name["slow"].error, "timeout")
        self.assertTrue(report.any_failed)

    def test_all_sources_failed(self):
        def a():
            raise ValueError("a fail")

        def b():
            raise KeyError("b fail")

        results, report = query_parallel({"a": a, "b": b}, timeout=10)
        self.assertEqual(results, [])
        self.assertTrue(report.all_failed)


if __name__ == "__main__":
    unittest.main()
