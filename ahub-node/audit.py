"""Structured audit logging for ahub-node."""

import json
import sys
import time
from pathlib import Path
from typing import Optional

_log_file = None


def init(log_path: Optional[str] = None):
    """Initialize audit logger. If log_path is None, log to stderr only."""
    global _log_file
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        _log_file = open(log_path, "a")


def log(tool: str, params: dict, result_status: str, caller: str = "unknown"):
    """Write one audit entry as JSON line."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "caller": caller,
        "tool": tool,
        "params": _truncate_params(params),
        "status": result_status,
    }
    line = json.dumps(entry, ensure_ascii=False)
    print(f"[audit] {line}", file=sys.stderr)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def _truncate_params(params: dict, max_len: int = 200) -> dict:
    """Truncate long param values for log readability."""
    out = {}
    for k, v in params.items():
        s = str(v)
        out[k] = s[:max_len] + "..." if len(s) > max_len else s
    return out
