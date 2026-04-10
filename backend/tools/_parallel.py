"""Parallel multi-source query framework with degradation tracking.

When a tool needs data from multiple providers (Google Flights + Bing +
Fliggy), this module fires all queries simultaneously using ThreadPool
and merges results. Failed sources are logged and skipped — they don't
block or crash the overall search.

Design notes:

1. WHY ThreadPoolExecutor, not ProcessPoolExecutor?
   Our workload is IO-bound (waiting for HTTP responses from SerpAPI,
   Firecrawl, etc.). Threads release the GIL during IO waits, so they
   achieve true parallelism for this use case. Processes would add
   ~100ms startup overhead + inter-process serialization cost for zero
   benefit — the CPU isn't the bottleneck, the network is.

2. WHY as_completed, not map?
   `as_completed` returns results in the order they FINISH, not the
   order they were submitted. This means if Bing responds in 0.5s but
   Google takes 2s, we start processing Bing's results immediately.
   For user-facing latency, this matters.

3. WHY per-result _source and _degraded fields?
   A single search might partially degrade (Google succeeded, Bing
   failed). Per-result metadata lets the frontend show a ⚠️ only on
   the degraded items, not blanket the whole page. See design notes
   in the parent module's docstring.

Usage:
    from tools._parallel import query_parallel

    results, report = query_parallel({
        "google_flights": lambda: call_serpapi(...),
        "bing": lambda: call_serpapi_bing(...),
    })
    # results: list[dict] with _source on each
    # report: DegradationReport with per-source status
"""

from __future__ import annotations
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SourceStatus:
    """Outcome of one source in a parallel query."""
    name: str
    ok: bool
    count: int = 0
    error: str = ""


@dataclass
class DegradationReport:
    """Summary of which sources succeeded/failed in a parallel query.

    Designed to be (1) logged for debugging, (2) included in agent
    status messages for the user, (3) inspectable by the supervisor.
    """
    sources: list[SourceStatus] = field(default_factory=list)

    @property
    def any_failed(self) -> bool:
        return any(not s.ok for s in self.sources)

    @property
    def all_failed(self) -> bool:
        return all(not s.ok for s in self.sources)

    @property
    def succeeded(self) -> list[str]:
        return [s.name for s in self.sources if s.ok]

    @property
    def failed(self) -> list[str]:
        return [s.name for s in self.sources if not s.ok]

    def summary(self) -> str:
        """Human-readable one-liner for log messages and user notifications.

        Examples:
            "sources: google_flights(3) + bing(2)"
            "sources: google_flights(3) | FAILED: bing (timeout)"
            "ALL SOURCES FAILED: google_flights (timeout), bing (401)"
        """
        parts = []
        for s in self.sources:
            if s.ok:
                parts.append(f"{s.name}({s.count})")
            else:
                parts.append(f"FAILED:{s.name}({s.error})")
        return " | ".join(parts)


def query_parallel(
    sources: dict[str, callable],
    timeout: float = 15.0,
) -> tuple[list[dict], DegradationReport]:
    """Fire multiple data source queries in parallel, merge results.

    Args:
        sources: Mapping of source_name -> callable. Each callable
                 should return list[dict] on success or raise on failure.
        timeout: Max seconds to wait for ALL sources. Sources that
                 haven't returned by then are treated as failed.

    Returns:
        (merged_results, report):
        - merged_results: list[dict], each dict has "_source" added.
        - report: DegradationReport summarizing per-source outcomes.
          Use report.any_failed to decide whether to warn the user.

    Teaching note — WHY return a report alongside results?
    Because the caller (agent or supervisor) needs to make TWO
    different decisions based on two different signals:
    - "What data do I have?" → results list
    - "Should I warn the user about quality?" → report.any_failed
    Bundling both into one return avoids the caller having to re-derive
    degradation info from the results.
    """
    if not sources:
        return [], DegradationReport()

    all_results: list[dict] = []
    report = DegradationReport()

    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        future_to_name = {
            pool.submit(fn): name
            for name, fn in sources.items()
        }

        for future in as_completed(future_to_name, timeout=timeout):
            name = future_to_name[future]
            try:
                results = future.result()
                if not results:
                    # Source returned empty — treat as soft failure
                    report.sources.append(SourceStatus(name=name, ok=False, error="empty"))
                    logger.warning("parallel: %s returned empty results", name)
                    continue

                # Tag each result with its source
                for r in results:
                    r["_source"] = name
                    r["_degraded"] = False
                all_results.extend(results)
                report.sources.append(SourceStatus(name=name, ok=True, count=len(results)))
                logger.info("parallel: %s returned %d results", name, len(results))

            except Exception as e:
                error_msg = f"{e.__class__.__name__}: {str(e)[:100]}"
                report.sources.append(SourceStatus(name=name, ok=False, error=error_msg))
                logger.warning("parallel: %s failed — %s", name, error_msg)

        # Check for sources that timed out (not in as_completed results)
        completed_names = {future_to_name[f] for f in future_to_name if f.done()}
        for name in sources:
            if name not in completed_names and name not in [s.name for s in report.sources]:
                report.sources.append(SourceStatus(name=name, ok=False, error="timeout"))
                logger.warning("parallel: %s timed out after %.1fs", name, timeout)

    # Log the overall summary
    logger.info("parallel query done: %s", report.summary())

    return all_results, report
