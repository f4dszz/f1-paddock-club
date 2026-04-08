"""Logging configuration for the F1 Paddock Club backend.

Call `setup_logging()` once at the top of each entry point (graph.py,
main.py). It attaches a file handler that writes to
`backend/logs/backend.log` in UTF-8, append mode. The existing CLI
print output and uvicorn's own console logs are left untouched — this
adds a file-based audit trail alongside them, it doesn't replace them.

The log level can be overridden at runtime via the LOG_LEVEL env var
(DEBUG, INFO, WARNING, ERROR). Defaults to INFO.
"""

from __future__ import annotations
import logging
import os
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_FILE = _LOG_DIR / "backend.log"
_FORMAT = "[%(asctime)s] %(levelname)-8s %(name)-24s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging() -> Path:
    """Attach a file handler to the root logger. Safe to call repeatedly.

    Returns the path to the log file so callers can mention it in startup
    messages if they want.
    """
    global _configured
    if _configured:
        return _LOG_FILE

    _LOG_DIR.mkdir(exist_ok=True)

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid stacking duplicate file handlers if something else already
    # added one pointing at the same file.
    for h in root.handlers:
        if isinstance(h, logging.FileHandler):
            try:
                if Path(h.baseFilename).resolve() == _LOG_FILE.resolve():
                    _configured = True
                    return _LOG_FILE
            except Exception:
                pass

    file_handler = logging.FileHandler(_LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    root.addHandler(file_handler)

    logging.getLogger(__name__).info(
        "logging initialized — level=%s file=%s", level_name, _LOG_FILE
    )

    _configured = True
    return _LOG_FILE
