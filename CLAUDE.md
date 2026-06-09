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

## Test Harness 执行规则

1. 执行提测任务时，必须先解析为 TestPlan 并通过 Pydantic 验证
2. 必须通过 harness 编排引擎逐步执行，不能跳步骤
3. 无对应 MCP 节点的硬件标记 skip，不模拟结果
4. 环境创建后不自动删除，标记保留信息供再进入
5. 网络问题按 `harness/config.yaml` 代理策略处理
6. 未知错误不猜测解决方案，记录完整 stderr 并停止
7. 服务类操作必须后台启动 + 健康检查确认就绪
8. 遇到错误先查 `harness/knowledge.yaml`，匹配则按方案处理
9. 用户教你解决测试错误时，必须将 pattern + solution 写入 `harness/knowledge.yaml`
10. install/service_start/test_run 禁止在宿主机直接执行，必须在 docker 或 venv 中。生成 TestPlan 时注意正确归类 stage type

See `harness/skill.md` for full harness specification.
