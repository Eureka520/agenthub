# AgentHub Project Rules

## Remote Machine Operations

When operating remote machines (any node connected via MCP, e.g. node-A100-594):

1. **ALWAYS use MCP tools** — never SSH, SCP, or direct shell access to remote machines
2. **Prefer specific tools** over generic shell_exec:
   - `file_read` over `shell_exec("cat ...")`
   - `file_write` over `shell_exec("echo > ...")`
   - `container_exec` over `shell_exec("docker exec ...")`
   - `container_manage(action="list")` over `shell_exec("docker ps")`
   - `system_info` over multiple shell_exec calls for status
3. **Handle security responses**:
   - `confirmation_required` → show user the risk, get approval, retry with confirm_token
   - `blocked` → inform user, do NOT attempt workarounds
4. **Workflow**: check state → operate → verify result
5. **Always call `system_info()` first** when beginning work on a remote node

See `docs/remote-ops-rules.md` for full specification.
