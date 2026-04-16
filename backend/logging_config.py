"""Logging configuration for the F1 Paddock Club backend.

Call `setup_logging()` once at the top of each entry point (graph.py,
main.py). It attaches a file handler that writes to
`backend/logs/backend_YYYY-MM-DD.log` in UTF-8, append mode. The existing
CLI print output and uvicorn's own console logs are left untouched —
this adds a file-based audit trail alongside them, it doesn't replace
them.

The log file name is dated per startup so logs from different sessions
are easy to separate. Same-day restarts append to the same dated file.

The log level can be overridden at runtime via the LOG_LEVEL env var
(DEBUG, INFO, WARNING, ERROR). Defaults to INFO.
"""

from __future__ import annotations
import logging
import os
from datetime import date
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent / "logs"
_FORMAT = "[%(asctime)s] %(levelname)-8s %(name)-24s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False
_active_log_file: Path | None = None


def _today_log_file() -> Path:
    return _LOG_DIR / f"backend_{date.today().isoformat()}.log"


def setup_logging() -> Path:
    """Attach a file handler to the root logger. Safe to call repeatedly.

    Returns the path to the log file so callers can mention it in startup
    messages if they want.
    """
    global _configured, _active_log_file
    if _configured and _active_log_file is not None:
        return _active_log_file

    _LOG_DIR.mkdir(exist_ok=True)

    log_file = _today_log_file()
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid stacking duplicate file handlers if something else already
    # added one pointing at the same file.
    for h in root.handlers:
        if isinstance(h, logging.FileHandler):
            try:
                if Path(h.baseFilename).resolve() == log_file.resolve():
                    _configured = True
                    _active_log_file = log_file
                    return log_file
            except Exception:
                pass

    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    root.addHandler(file_handler)

    logging.getLogger(__name__).info(
        "logging initialized — level=%s file=%s", level_name, log_file
    )

    _configured = True
    _active_log_file = log_file
    return log_file
