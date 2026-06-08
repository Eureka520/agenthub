# Remote Machine Operation Rules

This document defines the standard rules for AI agents operating remote machines via ahub-node MCP Server.

## Core Principle

**All remote machine operations MUST go through the MCP tools provided by ahub-node.** Never use SSH, SCP, or direct network commands to access remote machines. The MCP server provides security enforcement, audit logging, and confirmation workflows that cannot be bypassed.

## Available Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `shell_exec(cmd, cwd, timeout)` | Execute shell commands on host | System admin, package management, nvidia-smi, docker commands |
| `container_exec(container_id, cmd, cwd, timeout)` | Execute commands inside a container | Training, inference, pip install, testing inside containers |
| `container_manage(action, ...)` | Create/list/stop/remove containers | Lifecycle management (action: create/list/stop/rm) |
| `file_read(path, container_id)` | Read file contents | View configs, logs, results (prefer over shell_exec cat) |
| `file_write(path, content, container_id)` | Write file contents | Upload scripts, modify configs (prefer over shell_exec echo/tee) |
| `system_info()` | Get system status | Check CPU/memory/GPU/disk/containers before operations |
| `transfer_file(src, dest, container_id, direction)` | Transfer files host<->container | Move datasets, models, scripts between host and containers |

## Tool Selection Priority

Always prefer the most specific tool:

1. `file_read` over `shell_exec("cat ...")`
2. `file_write` over `shell_exec("echo ... > ...")`
3. `container_exec` over `shell_exec("docker exec ...")`
4. `container_manage(action="list")` over `shell_exec("docker ps")`
5. `system_info` over `shell_exec("nvidia-smi")` + `shell_exec("free -h")` separately

## Security Rules

1. **Confirmation workflow**: If a tool returns `status: "confirmation_required"`, present the risk to the user and ask for explicit approval. Only re-call with the provided `confirm_token` after user confirms.
2. **Blocked commands**: If a tool returns `status: "blocked"`, do NOT attempt workarounds. Inform the user the operation is blocked by security policy.
3. **Never bypass**: Do not attempt to circumvent security by encoding commands, splitting into multiple calls, or using alternative syntax to achieve a blocked operation.
4. **Check before modifying**: Always call `system_info()` or `file_read` to understand current state before making changes.

## Workflow Pattern

```
1. system_info()                          → understand current state
2. file_read / container_manage(list)     → inspect specifics
3. shell_exec / container_exec            → perform operation
4. file_read / system_info()              → verify result
```

## Error Handling

- On `confirmation_required`: show user the command and risk, ask permission, retry with token
- On `blocked`: inform user, suggest alternative approach
- On `exit_code != 0`: analyze stderr, attempt fix, do not retry blindly
- On timeout: consider increasing timeout param or breaking operation into smaller steps
