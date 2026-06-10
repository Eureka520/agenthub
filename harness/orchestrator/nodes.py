"""Node executors — one function per stage type with fixed execution strategies."""

import time
import re
from pathlib import Path
from typing import Callable

import yaml

from harness.error_handler import ErrorHandler
from harness.orchestrator.state import HarnessState

# Load config
_config_path = Path(__file__).parent.parent / "config.yaml"
with open(_config_path) as f:
    CONFIG = yaml.safe_load(f)

_error_handler = ErrorHandler()


class McpClient:
    """Real MCP client — connects to ahub-node via SSE + Bearer token."""

    def __init__(self, url: str = None, token: str = None):
        mcp_cfg = CONFIG.get("mcp", {})
        self.url = url or mcp_cfg.get("url", "")
        self.token = token or mcp_cfg.get("token", "")
        self._headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _call(self, tool_name: str, args: dict) -> dict:
        """Synchronous wrapper around async MCP call."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, self._async_call(tool_name, args)).result()
            return asyncio.run(self._async_call(tool_name, args))
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": -1}

    async def _async_call(self, tool_name: str, args: dict) -> dict:
        import json as _json
        from mcp.client.sse import sse_client
        from mcp import ClientSession
        async with sse_client(self.url, headers=self._headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                return _json.loads(result.content[0].text)

    def shell_exec(self, cmd: str, cwd: str = "/", timeout: int = 60) -> dict:
        return self._call("shell_exec", {"cmd": cmd, "cwd": cwd, "timeout": timeout})

    def container_exec(self, container_id: str, cmd: str, timeout: int = 60) -> dict:
        return self._call("container_exec", {"container_id": container_id, "cmd": cmd, "timeout": timeout})

    def container_manage(self, **kwargs) -> dict:
        return self._call("container_manage", kwargs)

    def file_read(self, path: str, container_id: str = "") -> dict:
        return self._call("file_read", {"path": path, "container_id": container_id})

    def system_info(self) -> dict:
        return self._call("system_info", {})


# Stage types that MUST run inside docker or venv (protect host machine)
REQUIRE_ISOLATED_ENV = {"install", "service_start", "test_run"}


def execute_stage(stage: dict, state: dict, mcp: McpClient) -> dict:
    """Route to the correct executor based on stage type."""
    # Host protection: refuse to run install/service/test directly on host
    if stage["type"] in REQUIRE_ISOLATED_ENV:
        container = _get_container_for_env(state, stage)
        venv = _get_venv_for_env(state, stage)
        if not container and not venv:
            return {"status": "fail", "errors": [{"message": f"拒绝在宿主机直接执行 {stage['type']}，必须在 docker 或 venv 中操作"}]}

    executor = EXECUTORS.get(stage["type"], execute_custom)
    start = time.time()
    try:
        result = executor(stage, state, mcp)
    except Exception as e:
        result = {"status": "fail", "errors": [{"message": str(e)}]}
    result["duration"] = round(time.time() - start, 1)
    return result


def execute_container_create(stage: dict, state: dict, mcp: McpClient) -> dict:
    env_id = stage["env_id"]
    env_def = _find_env(state, env_id)
    if not env_def or env_def.get("env_type") != "docker":
        return {"status": "fail", "errors": [{"message": f"No docker env definition for {env_id}"}]}

    # Select free GPU before creating container
    gpu_id = _select_free_gpu(mcp)
    state["gpu_device"] = gpu_id

    docker = env_def.get("docker", {})
    result = mcp.container_manage(
        action="create",
        image=docker.get("image", "python:3.10-slim"),
        name=f"harness_{env_id}",
        gpu=docker.get("gpu", False),
        volumes=",".join(docker.get("volumes", [])),
    )
    if "error" in str(result.get("stderr", "")):
        return {"status": "fail", "errors": [{"message": result.get("stderr", "")}]}

    state.setdefault("environments", {})[env_id] = {
        "container_name": f"harness_{env_id}",
        "gpu_device": gpu_id,
        "status": "created",
        "can_reenter": True,
    }
    return {"status": "ok", "gpu_device": gpu_id}


def execute_venv_create(stage: dict, state: dict, mcp: McpClient) -> dict:
    env_id = stage["env_id"]
    env_def = _find_env(state, env_id)
    venv_path = env_def.get("venv", {}).get("path", f"/workspace/{env_id}") if env_def else f"/workspace/{env_id}"
    python = env_def.get("venv", {}).get("python", "python3") if env_def else "python3"

    # Execute in parent container if exists
    container = _get_container_for_env(state, stage)
    if container:
        result = mcp.container_exec(container, f"{python} -m venv {venv_path}")
    else:
        result = mcp.shell_exec(f"{python} -m venv {venv_path}")

    if result.get("exit_code", -1) != 0:
        return {"status": "fail", "errors": [{"message": result.get("stderr", "")}]}

    state.setdefault("environments", {})[env_id] = {
        "venv_path": venv_path,
        "status": "created",
        "can_reenter": True,
    }
    return {"status": "ok"}


def execute_install(stage: dict, state: dict, mcp: McpClient) -> dict:
    commands = _resolve_commands(stage, state)
    container = _get_container_for_env(state, stage)
    network = CONFIG.get("network", {})
    max_retry = network.get("download_retry", 3)
    poll_interval = CONFIG.get("defaults", {}).get("poll_interval", 10)

    results = []
    for cmd in commands:
        success = False
        last_stderr = ""
        for attempt in range(max_retry):
            exec_cmd = _apply_proxy(cmd, attempt, network)
            # Fire-and-poll: submit background + poll marker
            stage_id = stage["id"]
            marker = f"/tmp/harness_{stage_id}_{attempt}.marker"
            log_file = f"/tmp/harness_{stage_id}_{attempt}.log"
            bg_cmd = f"bash -c '{exec_cmd} > {log_file} 2>&1; echo $? > {marker}' &"

            if container:
                mcp.container_exec(container, bg_cmd, timeout=5)
            else:
                mcp.shell_exec(bg_cmd, timeout=5)

            # Poll for completion
            deadline = time.time() + stage.get("timeout", 3600)
            while time.time() < deadline:
                if container:
                    r = mcp.container_exec(container, f"cat {marker} 2>/dev/null", timeout=5)
                else:
                    r = mcp.shell_exec(f"cat {marker} 2>/dev/null", timeout=5)
                content = r.get("stdout", "").strip()
                if content == "0":
                    success = True
                    results.append({"cmd": cmd, "status": "ok"})
                    if attempt > 0 and last_stderr:
                        _error_handler.learn(
                            stderr=last_stderr,
                            solution=f"retry with proxy/mirror (attempt {attempt})",
                        )
                    break
                elif content:  # non-zero exit code
                    if container:
                        log_r = mcp.container_exec(container, f"tail -20 {log_file}", timeout=5)
                    else:
                        log_r = mcp.shell_exec(f"tail -20 {log_file}", timeout=5)
                    last_stderr = log_r.get("stdout", "")
                    match = _error_handler.classify(last_stderr)
                    if match.level == "L3":
                        return {"status": "fail", "errors": [{"message": last_stderr, "level": "L3"}], "commands_run": results}
                    break  # retry with next attempt
                time.sleep(poll_interval)
            else:
                # Timeout waiting for marker
                return {"status": "timeout", "errors": [{"message": f"Timeout waiting for: {cmd}"}], "commands_run": results}

            if success:
                break
        if not success:
            return {"status": "fail", "errors": [{"message": f"Failed after {max_retry} retries: {cmd}"}], "commands_run": results}

    # Verify if specified
    if stage.get("verify"):
        if container:
            vr = mcp.container_exec(container, stage["verify"])
        else:
            vr = mcp.shell_exec(stage["verify"])
        if vr.get("exit_code", -1) != 0:
            return {"status": "fail", "errors": [{"message": f"Verify failed: {vr.get('stderr', '')}"}], "commands_run": results}

    return {"status": "ok", "commands_run": results}


def execute_service_start(stage: dict, state: dict, mcp: McpClient) -> dict:
    """Fixed strategy: background launch via script + health_check polling. Pins to selected GPU."""
    cmd = stage["commands"][0] if stage.get("commands") else ""
    if not cmd:
        return {"status": "fail", "errors": [{"message": "No command for service_start"}]}

    container = _get_container_for_env(state, stage)
    log_file = f"/tmp/{stage['id']}.log"
    timeout = stage.get("timeout", CONFIG["defaults"]["service_start_timeout"])
    interval = CONFIG["defaults"]["health_check_interval"]
    gpu_id = state.get("gpu_device", "")

    # Fire: launch in background via bash -c with exec (immediate return)
    exec_cmd = _wrap_gpu_env(cmd, gpu_id)
    bg_cmd = f"bash -c 'exec {exec_cmd}' > {log_file} 2>&1 &"
    if container:
        mcp.container_exec(container, bg_cmd, timeout=5)
    else:
        mcp.shell_exec(bg_cmd, timeout=5)

    # Poll: health_check
    health_check = stage.get("health_check", "")
    if not health_check:
        time.sleep(5)
        return {"status": "ok", "log": log_file}

    deadline = time.time() + timeout
    while time.time() < deadline:
        if container:
            r = mcp.container_exec(container, health_check, timeout=5)
        else:
            r = mcp.shell_exec(health_check, timeout=5)
        if r.get("exit_code", -1) == 0:
            return {"status": "ok", "log": log_file}
        time.sleep(interval)

    # Timeout — read log for diagnostics
    if container:
        log = mcp.file_read(log_file, container_id=container)
    else:
        log = mcp.file_read(log_file)
    return {"status": "timeout", "log": log.get("content", ""), "errors": [{"message": f"Service did not become healthy within {timeout}s"}]}


def execute_test_run(stage: dict, state: dict, mcp: McpClient) -> dict:
    container = _get_container_for_env(state, stage)
    timeout = stage.get("timeout", 7200)
    gpu_id = state.get("gpu_device", "")
    results = []

    # Start GPU/CPU monitoring in background
    monitor_log = f"/tmp/gpu_monitor_{stage['id']}.csv"
    if gpu_id and container:
        mcp.container_exec(container, f"nvidia-smi dmon -i {gpu_id} -d 5 -o DT > {monitor_log} 2>&1 &", timeout=5)
    elif gpu_id:
        mcp.shell_exec(f"nvidia-smi dmon -i {gpu_id} -d 5 -o DT > {monitor_log} 2>&1 &", timeout=5)
    state["gpu_monitor_log"] = monitor_log

    for cmd in stage.get("commands", []):
        exec_cmd = _wrap_gpu_env(cmd, gpu_id)
        if container:
            r = mcp.container_exec(container, exec_cmd, timeout=timeout)
        else:
            r = mcp.shell_exec(exec_cmd, timeout=timeout)

        if r.get("exit_code", -1) != 0:
            match = _error_handler.classify(r.get("stderr", ""))
            return {"status": "fail", "errors": [{"message": r.get("stderr", ""), "level": match.level}], "commands_run": results, "logs": r.get("stdout", ""), "gpu_monitor_log": monitor_log}
        results.append({"cmd": cmd, "status": "ok"})

    return {"status": "ok", "commands_run": results, "gpu_monitor_log": monitor_log}


def execute_collect(stage: dict, state: dict, mcp: McpClient) -> dict:
    container = _get_container_for_env(state, stage)
    results = []
    for cmd in stage.get("commands", []):
        if container:
            r = mcp.container_exec(container, cmd, timeout=300)
        else:
            r = mcp.shell_exec(cmd, timeout=300)
        results.append({"cmd": cmd, "exit_code": r.get("exit_code", -1)})
    return {"status": "ok", "commands_run": results}


def execute_custom(stage: dict, state: dict, mcp: McpClient) -> dict:
    """Fallback: execute commands sequentially, no special strategy."""
    container = _get_container_for_env(state, stage)
    for cmd in stage.get("commands", []):
        if container:
            r = mcp.container_exec(container, cmd, timeout=stage.get("timeout", 3600))
        else:
            r = mcp.shell_exec(cmd, timeout=stage.get("timeout", 3600))
        if r.get("exit_code", -1) != 0:
            return {"status": "fail", "errors": [{"message": r.get("stderr", "")}]}
    return {"status": "ok"}


# ── Helpers ─────────────────────────────────────────────────────────────────

def _find_env(state: dict, env_id: str) -> dict:
    for env in state.get("test_plan", {}).get("environments", []):
        if env.get("env_id") == env_id:
            return env
    return {}


def _get_container_for_env(state: dict, stage: dict) -> str:
    env_id = stage.get("env_id", "")
    envs = state.get("environments", {})
    env_info = envs.get(env_id, {})
    return env_info.get("container_name", "")


def _get_venv_for_env(state: dict, stage: dict) -> str:
    env_id = stage.get("env_id", "")
    envs = state.get("environments", {})
    env_info = envs.get(env_id, {})
    return env_info.get("venv_path", "")


def _resolve_commands(stage: dict, state: dict) -> list[str]:
    alts = stage.get("alternatives", [])
    if not alts:
        return stage.get("commands", [])
    # Simple condition eval based on state
    for i, alt in enumerate(alts):
        if _eval_condition(alt.get("condition", ""), state):
            state.setdefault("resolved_alternatives", {})[stage["id"]] = f"alt_{i}"
            return alt["commands"]
    state.setdefault("resolved_alternatives", {})[stage["id"]] = "main"
    return stage.get("commands", [])


def _eval_condition(condition: str, state: dict) -> bool:
    """Simple condition evaluation: 'cuda_version < 13.0'"""
    if not condition:
        return False
    # Extract cuda version from system info if available
    sys_info = state.get("system_info", {})
    cuda_ver = sys_info.get("cuda_version", "13.0")
    try:
        if "cuda_version" in condition:
            parts = condition.replace("cuda_version", "").strip().split()
            if len(parts) == 2:
                op, val = parts
                cv = float(cuda_ver)
                tv = float(val)
                if op == "<":
                    return cv < tv
                elif op == "<=":
                    return cv <= tv
                elif op == ">":
                    return cv > tv
    except (ValueError, IndexError):
        pass
    return False


def _apply_proxy(cmd: str, attempt: int, network: dict) -> str:
    """Apply proxy/mirror based on retry attempt. Handles pip and hf commands."""
    proxies = network.get("proxies", [])
    mirrors = network.get("pip_mirrors", [])
    hf_mirrors = network.get("hf_mirrors", [])
    primary_proxy = network.get("primary_proxy", "http://agent.baidu.com:8188")

    is_pip = "pip" in cmd
    is_hf = "hf " in cmd or "huggingface-cli" in cmd

    if attempt == 0:
        # Direct attempt — no proxy
        if is_pip and mirrors:
            return cmd + f" -i {mirrors[0]}"
        if is_hf and hf_mirrors and hf_mirrors[0]:
            return f"HF_ENDPOINT={hf_mirrors[0]} {cmd}"
        return cmd

    # Subsequent attempts: use primary proxy (agent.baidu.com:8188)
    prefix = f"export http_proxy={primary_proxy} https_proxy={primary_proxy} && "
    suffix = " && unset http_proxy https_proxy"

    if is_pip and mirrors:
        mirror_idx = attempt % len(mirrors)
        cmd = cmd + f" -i {mirrors[mirror_idx]}"
    elif is_hf and hf_mirrors:
        mirror_idx = attempt % len(hf_mirrors)
        if hf_mirrors[mirror_idx]:
            cmd = f"HF_ENDPOINT={hf_mirrors[mirror_idx]} {cmd}"

    return f"{prefix}{cmd}{suffix}"


def _select_free_gpu(mcp: McpClient) -> str:
    """Query system_info and return the ID of a free GPU (lowest memory usage)."""
    info = mcp.system_info()
    gpus = info.get("gpu", [])
    if not gpus or isinstance(gpus, str):
        return "0"
    # Find GPU with lowest memory usage
    free_gpus = [g for g in gpus if int(g.get("memory_used_mb", "99999")) < 100]
    if free_gpus:
        return free_gpus[0]["id"]
    # No completely free GPU — pick lowest utilization
    sorted_gpus = sorted(gpus, key=lambda g: int(g.get("memory_used_mb", "0")))
    return sorted_gpus[0]["id"]


def _wrap_gpu_env(cmd: str, gpu_id: str) -> str:
    """Wrap command with CUDA_VISIBLE_DEVICES to pin to selected GPU."""
    if not gpu_id:
        return cmd
    return f"CUDA_VISIBLE_DEVICES={gpu_id} {cmd}"


EXECUTORS: dict[str, Callable] = {
    "container_create": execute_container_create,
    "venv_create": execute_venv_create,
    "install": execute_install,
    "service_start": execute_service_start,
    "test_run": execute_test_run,
    "collect": execute_collect,
    "custom": execute_custom,
}
