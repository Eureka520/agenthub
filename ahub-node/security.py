"""Security policy for ahub-node MCP Server."""

import re
import time
import uuid
from typing import Optional

# Pending confirmations: token -> {cmd, expires}
_pending: dict[str, dict] = {}


def load_patterns(config: dict) -> tuple[list, list]:
    """Compile regex patterns from config."""
    sec = config.get("security", {})
    blocked = [re.compile(p) for p in sec.get("blocked_patterns", [])]
    confirm = [re.compile(p) for p in sec.get("confirm_patterns", [])]
    return blocked, confirm


def classify_command(cmd: str, blocked: list, confirm: list) -> str:
    """Classify a command: 'free' | 'confirm' | 'blocked'."""
    for pat in blocked:
        if pat.search(cmd):
            return "blocked"
    for pat in confirm:
        if pat.search(cmd):
            return "confirm"
    return "free"


def create_confirmation(cmd: str, expire_seconds: int = 300) -> str:
    """Create a one-time confirmation token for a dangerous command."""
    token = uuid.uuid4().hex[:16]
    _pending[token] = {"cmd": cmd, "expires": time.time() + expire_seconds}
    # Clean expired
    now = time.time()
    expired = [k for k, v in _pending.items() if v["expires"] < now]
    for k in expired:
        del _pending[k]
    return token


def validate_confirmation(token: Optional[str], cmd: str) -> bool:
    """Validate a confirmation token matches the command and is not expired."""
    if not token or token not in _pending:
        return False
    entry = _pending[token]
    if time.time() > entry["expires"]:
        del _pending[token]
        return False
    if entry["cmd"] != cmd:
        return False
    del _pending[token]
    return True
