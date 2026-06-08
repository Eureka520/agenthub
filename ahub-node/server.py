#!/usr/bin/env python3
"""ahub-node — AgentHub remote compute node MCP Server.

Deploy on target machines to allow AI agents to execute commands,
manage containers, and perform ML workflows without SSH credentials.

Usage:
    python server.py [--config config.yaml] [--port 9100]
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import yaml
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import audit
from security import (
    check_path,
    classify_command,
    create_confirmation,
    load_patterns,
    validate_confirmation,
)

# ── Load config ─────────────────────────────────────────────────────────────

CONFIG_PATH = os.environ.get("AHUB_NODE_CONFIG", str(Path(__file__).parent / "config.yaml"))

with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

SERVER_CFG = CONFIG.get("server", {})
SEC_CFG = CONFIG.get("security", {})
MAX_TIMEOUT = SEC_CFG.get("max_timeout", 7200)
MAX_OUTPUT = SEC_CFG.get("max_output_bytes", 1048576)
CONFIRM_EXPIRE = SEC_CFG.get("confirm_expire_seconds", 300)
BLOCKED_PATHS = SEC_CFG.get("blocked_paths", [])

BLOCKED_PAT, CONFIRM_PAT = load_patterns(CONFIG)

# ── Auth ───────────────────────────────────────────────────────────────────

AUTH_TOKENS: dict[str, str] = {}  # token_value -> caller_name
for entry in SERVER_CFG.get("tokens", []):
    AUTH_TOKENS[entry["token"]] = entry.get("name", "unknown")

# ── Audit ──────────────────────────────────────────────────────────────────

audit.init(SEC_CFG.get("audit_log"))

# ── MCP Server ──────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="ahub-node",
    instructions="Remote compute node for AgentHub. Provides shell execution, "
    "Docker container management, file operations, and system monitoring.",
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
        allowed_hosts=["*"],
    ),
)

# ── Auth Middleware ────────────────────────────────────────────────────────

_current_caller = "anonymous"


def _authenticate_request(headers: dict) -> str:
    """Validate Bearer token from request headers. Returns caller name or empty string."""
    if not AUTH_TOKENS:
        return "anonymous"
    auth = headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return ""
    return AUTH_TOKENS.get(auth[7:], "")

# ── Helper ──────────────────────────────────────────────────────────────────


def _run(cmd: str, timeout: int = 60, cwd: Optional[str] = None, env: Optional[dict] = None) -> dict:
    """Run a shell command and return structured result."""
    timeout = min(timeout, MAX_TIMEOUT)
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd, env={**os.environ, **(env or {})}
        )
        stdout = proc.stdout[:MAX_OUTPUT] if proc.stdout else ""
        stderr = proc.stderr[:MAX_OUTPUT] if proc.stderr else ""
        return {"stdout": stdout, "stderr": stderr, "exit_code": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Command timed out after {timeout}s", "exit_code": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": -1}


def _check_security(cmd: str, confirm_token: Optional[str] = None) -> Optional[dict]:
    """Check command against security policy. Returns error dict or None if OK."""
    level = classify_command(cmd, BLOCKED_PAT, CONFIRM_PAT)
    if level == "blocked":
        return {"status": "blocked", "message": f"Command is permanently blocked by security policy: {cmd}"}
    if level == "confirm":
        if confirm_token:
            if validate_confirmation(confirm_token, cmd):
                return None  # Confirmed, proceed
            return {"status": "error", "message": "Invalid or expired confirmation token"}
        token = create_confirmation(cmd, CONFIRM_EXPIRE)
        return {
            "status": "confirmation_required",
            "command": cmd,
            "risk": "This command may cause data loss or service disruption",
            "confirm_token": token,
            "message": f"Dangerous command detected. Re-call with confirm_token='{token}' to execute.",
        }
    return None  # Free to execute


# ── Tools ───────────────────────────────────────────────────────────────────


@mcp.tool()
def shell_exec(cmd: str, cwd: str = "/", timeout: int = 60, confirm_token: str = "") -> dict:
    """Execute a shell command on the host machine.

    Args:
        cmd: Shell command to execute
        cwd: Working directory (default: /)
        timeout: Max execution time in seconds (max 7200)
        confirm_token: Confirmation token for dangerous commands (leave empty for safe commands)

    Returns:
        dict with stdout, stderr, exit_code — or confirmation_required status
    """
    check = _check_security(cmd, confirm_token or None)
    if check:
        audit.log("shell_exec", {"cmd": cmd, "cwd": cwd}, check.get("status", "denied"))
        return check
    result = _run(cmd, timeout=timeout, cwd=cwd)
    audit.log("shell_exec", {"cmd": cmd, "cwd": cwd}, f"exit:{result['exit_code']}")
    return result


@mcp.tool()
def container_exec(container_id: str, cmd: str, cwd: str = "", timeout: int = 60) -> dict:
    """Execute a command inside a Docker container.

    Args:
        container_id: Container ID or name
        cmd: Command to execute inside the container
        cwd: Working directory inside container (optional)
        timeout: Max execution time in seconds (max 7200)

    Returns:
        dict with stdout, stderr, exit_code
    """
    check = _check_security(cmd, None)
    if check:
        audit.log("container_exec", {"container_id": container_id, "cmd": cmd}, check.get("status", "denied"))
        return check
    docker_cmd = f"docker exec"
    if cwd:
        docker_cmd += f" -w {cwd}"
    docker_cmd += f" {container_id} bash -c {_shell_quote(cmd)}"
    result = _run(docker_cmd, timeout=timeout)
    audit.log("container_exec", {"container_id": container_id, "cmd": cmd}, f"exit:{result['exit_code']}")
    return result


@mcp.tool()
def container_manage(action: str, image: str = "", name: str = "",
                     gpu: bool = False, memory: str = "", ports: str = "",
                     volumes: str = "", confirm_token: str = "") -> dict:
    """Manage Docker containers (create, list, stop, remove).

    Args:
        action: One of: create, list, stop, rm
        image: Docker image (required for create)
        name: Container name (optional for create, required for stop/rm)
        gpu: Enable GPU access (for create)
        memory: Memory limit e.g. "32g" (for create)
        ports: Port mapping e.g. "8080:80" (for create)
        volumes: Volume mounts e.g. "/data:/data" (for create)
        confirm_token: Required for rm action

    Returns:
        dict with operation result
    """
    if action == "list":
        result = _run("docker ps -a --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'")
        audit.log("container_manage", {"action": "list"}, f"exit:{result['exit_code']}")
        return result
    if action == "create":
        if not image:
            return {"status": "error", "message": "image is required for create"}
        cmd = f"docker run -d --init"
        if name:
            cmd += f" --name {name}"
        if gpu:
            cmd += " --gpus all"
        if memory:
            cmd += f" --memory {memory}"
        if ports:
            for p in ports.split(","):
                cmd += f" -p {p.strip()}"
        if volumes:
            for v in volumes.split(","):
                cmd += f" -v {v.strip()}"
        cmd += f" {image} sleep infinity"
        result = _run(cmd)
        audit.log("container_manage", {"action": "create", "image": image, "name": name}, f"exit:{result['exit_code']}")
        return result

    if action == "stop":
        target = name or ""
        if not target:
            return {"status": "error", "message": "name/container_id is required"}
        result = _run(f"docker stop {target}")
        audit.log("container_manage", {"action": "stop", "name": target}, f"exit:{result['exit_code']}")
        return result

    if action == "rm":
        target = name or ""
        if not target:
            return {"status": "error", "message": "name/container_id is required"}
        rm_cmd = f"docker rm -f {target}"
        check = _check_security(rm_cmd, confirm_token or None)
        if check:
            audit.log("container_manage", {"action": "rm", "name": target}, check.get("status", "denied"))
            return check
        result = _run(rm_cmd)
        audit.log("container_manage", {"action": "rm", "name": target}, f"exit:{result['exit_code']}")
        return result

    return {"status": "error", "message": f"Unknown action: {action}. Use: create, list, stop, rm"}


@mcp.tool()
def file_read(path: str, container_id: str = "") -> dict:
    """Read file contents from host or container.

    Args:
        path: Absolute path to the file
        container_id: If provided, read from inside this container

    Returns:
        dict with content or error
    """
    if not container_id and not check_path(path, BLOCKED_PATHS):
        audit.log("file_read", {"path": path}, "blocked")
        return {"error": f"Path is blocked by security policy: {path}"}
    if container_id:
        result = _run(f"docker exec {container_id} cat {_shell_quote(path)}")
        audit.log("file_read", {"path": path, "container_id": container_id}, f"exit:{result['exit_code']}")
        return {"content": result["stdout"], "error": result["stderr"]} if result["exit_code"] == 0 else result
    try:
        content = Path(path).read_text(errors="replace")[:MAX_OUTPUT]
        audit.log("file_read", {"path": path}, "ok")
        return {"content": content}
    except Exception as e:
        audit.log("file_read", {"path": path}, "error")
        return {"error": str(e)}


@mcp.tool()
def file_write(path: str, content: str, container_id: str = "") -> dict:
    """Write content to a file on host or inside a container.

    Args:
        path: Absolute path to write to
        content: File content
        container_id: If provided, write inside this container

    Returns:
        dict with success status
    """
    if not container_id and not check_path(path, BLOCKED_PATHS):
        audit.log("file_write", {"path": path}, "blocked")
        return {"success": False, "error": f"Path is blocked by security policy: {path}"}
    if container_id:
        cmd = f"docker exec -i {container_id} tee {_shell_quote(path)}"
        try:
            proc = subprocess.run(cmd, shell=True, input=content, capture_output=True, text=True, timeout=30)
            audit.log("file_write", {"path": path, "container_id": container_id}, f"exit:{proc.returncode}")
            if proc.returncode == 0:
                return {"success": True, "path": path}
            return {"success": False, "error": proc.stderr}
        except Exception as e:
            audit.log("file_write", {"path": path, "container_id": container_id}, "error")
            return {"success": False, "error": str(e)}
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content)
        audit.log("file_write", {"path": path}, "ok")
        return {"success": True, "path": path}
    except Exception as e:
        audit.log("file_write", {"path": path}, "error")
        return {"success": False, "error": str(e)}


@mcp.tool()
def system_info() -> dict:
    """Get comprehensive system information (CPU, memory, GPU, disk, containers).

    Returns:
        dict with cpu, memory, gpu, disk, containers, kernel info
    """
    audit.log("system_info", {}, "ok")
    info = {}

    # CPU
    try:
        cores = os.cpu_count() or 0
        load = os.getloadavg()
        info["cpu"] = {"cores": cores, "load_1m": load[0], "load_5m": load[1]}
    except Exception:
        info["cpu"] = {}

    # Memory
    mem = _run("free -b | awk '/Mem:/{print $2,$3,$7}'", timeout=5)
    if mem["exit_code"] == 0 and mem["stdout"].strip():
        parts = mem["stdout"].strip().split()
        if len(parts) == 3:
            total, used, avail = int(parts[0]), int(parts[1]), int(parts[2])
            info["memory"] = {
                "total_gb": round(total / 1e9, 1),
                "used_gb": round(used / 1e9, 1),
                "available_gb": round(avail / 1e9, 1),
            }

    # GPU
    gpu_result = _run("nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu "
                      "--format=csv,noheader,nounits", timeout=10)
    if gpu_result["exit_code"] == 0 and gpu_result["stdout"].strip():
        gpus = []
        for line in gpu_result["stdout"].strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 5:
                gpus.append({"id": parts[0], "name": parts[1],
                             "memory_used_mb": parts[2], "memory_total_mb": parts[3],
                             "utilization_percent": parts[4]})
        info["gpu"] = gpus
    else:
        info["gpu"] = "not available"

    # Disk
    disk = _run("df -h / | awk 'NR==2{print $2,$3,$4,$5}'", timeout=5)
    if disk["exit_code"] == 0 and disk["stdout"].strip():
        parts = disk["stdout"].strip().split()
        if len(parts) == 4:
            info["disk"] = {"total": parts[0], "used": parts[1], "free": parts[2], "use_percent": parts[3]}

    # Containers
    containers = _run("docker ps --format '{{.Names}} ({{.Image}}): {{.Status}}' 2>/dev/null", timeout=5)
    info["containers_running"] = len(containers["stdout"].strip().split("\n")) if containers["stdout"].strip() else 0
    info["containers_list"] = containers["stdout"].strip() if containers["stdout"].strip() else "none"

    # Kernel
    kernel = _run("uname -r", timeout=5)
    info["kernel"] = kernel["stdout"].strip()

    return info


@mcp.tool()
def transfer_file(src: str, dest: str, container_id: str = "", direction: str = "to_container") -> dict:
    """Transfer files between host and container.

    Args:
        src: Source file/directory path
        dest: Destination file/directory path
        container_id: Docker container ID or name
        direction: "to_container" (host→container) or "from_container" (container→host)

    Returns:
        dict with success status
    """
    if not container_id:
        return {"success": False, "error": "container_id is required"}

    if direction == "to_container":
        cmd = f"docker cp {_shell_quote(src)} {container_id}:{_shell_quote(dest)}"
    elif direction == "from_container":
        cmd = f"docker cp {container_id}:{_shell_quote(src)} {_shell_quote(dest)}"
    else:
        return {"success": False, "error": "direction must be 'to_container' or 'from_container'"}

    result = _run(cmd, timeout=300)
    if result["exit_code"] == 0:
        audit.log("transfer_file", {"src": src, "dest": dest, "direction": direction}, "ok")
        return {"success": True, "message": f"Transferred {src} → {dest}"}
    audit.log("transfer_file", {"src": src, "dest": dest, "direction": direction}, "error")
    return {"success": False, "error": result["stderr"]}


# ── Utilities ───────────────────────────────────────────────────────────────


def _shell_quote(s: str) -> str:
    """Shell-escape a string."""
    import shlex
    return shlex.quote(s)


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ahub-node MCP Server")
    parser.add_argument("--port", type=int, default=SERVER_CFG.get("port", 9100))
    parser.add_argument("--host", default=SERVER_CFG.get("host", "0.0.0.0"))
    args = parser.parse_args()

    # Set host/port on the FastMCP settings
    mcp.settings.host = args.host
    mcp.settings.port = args.port

    # Detect LAN IP
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        lan_ip = "127.0.0.1"

    print(f"\n  ahub-node MCP Server")
    print(f"  Listening: http://{lan_ip}:{args.port}")
    print(f"  Tools: {len(mcp._tool_manager._tools)} registered")
    print(f"  Auth: {len(AUTH_TOKENS)} token(s) configured" if AUTH_TOKENS else "  Auth: OPEN (no tokens configured)")
    print(f"\n  Claude Code settings.json:")
    print(f'  "mcpServers": {{ "node": {{ "type": "sse", "url": "http://{lan_ip}:{args.port}/sse" }} }}')
    print()

    mcp.run(transport="sse")
