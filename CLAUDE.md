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

**适用范围**：凡是需要在远端机器上运行代码/命令的任务，包括但不限于：提测验证、issue 复现、模型推理/训练、性能测试、数据分析、环境验证。只要涉及 MCP 远端执行，就必须走 harness 流程。不存在"这个任务比较简单所以直接操作"的例外。

**执行前自检（agent 在首次调用 MCP container_exec/shell_exec 前必须完成）**：
- [ ] TestPlan 是否已生成并获得用户 CLI 确认？
- [ ] AcceptanceSpec 是否已生成并冻结？
- [ ] HarnessState 是否已初始化（stage list + status tracking）？
任一项为否时，**禁止调用 container_exec / shell_exec**。违反此条视为 L3 错误——已产出的结果全部作废，必须从头重新执行 harness 流程。
agent 不得以"快速分析"、"先探索一下"、"简单验证"等理由绕过此自检。探索性操作同样必须在 TestPlan stage 中声明。

1. 执行上述任何任务时，**必须先生成 TestPlan** 并通过 Pydantic 验证，用户 CLI 确认后才能开始执行。禁止跳过 TestPlan 直接调用 MCP 工具执行。
1.1. **TestPlan 用户确认通过后，必须生成 AcceptanceSpec** 并向用户展示验收标准（required artifacts、metrics 阈值、exit_criteria、acceptance_mode）。用户 CLI 确认（[A]ccept/[E]dit/[R]egenerate）后冻结，作为后续 stage 门禁的硬约束。禁止跳过 AcceptanceSpec 确认直接执行。
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

## AcceptanceSpec / EvidenceManifest / ProgressLog（验收三件套）

11. 执行任务时，harness 在每个 stage 结束后自动执行：evidence 收集（扫描 `outputs/<stage>/` 生成 `manifest.json`）→ acceptance 检查（比对 `acceptance_spec.yaml` 中的 artifacts/metrics/exit_criteria）。不可跳过或绕过。
12. `ACCEPTANCE_FAILED` 为 L2 错误：先诊断（读 manifest + log 分类偶发/确定性/配置类），偶发类单次重试，确定性/配置类直接升 L3。不要盲目重试。
13. 最终报告必须包含三段：**验收结论**（PASS/FAIL 明细）/ **产物清单**（path/size/sha256/role）/ **关键事件时间线**（从 `progress_log.jsonl` 渲染）。缺任一段视为报告不完整。
14. 新任务类型只需在 `knowledge/priors.yaml` 的 `acceptance_templates` section 添加 task_type 模板，不要修改 harness 框架代码（`acceptance.py` / `evidence.py` / `progress_log.py` / `graph.py`）。
15. `acceptance_mode: advisory` 是显式逃生口——验收失败只记录不阻断，但报告中必须显著标注。仅用于探索性任务或历史回放，正式任务必须 `strict`。
16. 执行脚本可选写 `outputs/<stage>/manifest.hints.json` 给关键产物打 label/description；可选写 `outputs/<stage>/metrics.json` 提供结构化指标。未写时 harness 自动扫描 + LLM 兜底提取。
17. **Verifier 验证**：harness 在 `final_acceptance` 之后会自动运行 Verifier（独立 `claude -p` 子进程，只读工具 Read/Glob/Grep）。其结果写入 `outputs/verifier_verdict.json` 与最终报告。Worker 不得读取或修改 `verifier_verdict`，也不得绕过 Verifier。

See `docs/specs/2026-06-23-acceptance-spec-design.md` for full design specification.

## 先验知识

17. 执行任何操作前，先查阅 `knowledge/priors.yaml` 获取相关领域的推荐做法并遵循。priors 中有明确 preferred 的，优先使用而非现场发挥。
18. 当你通过尝试发现了更优的操作方式或解决了新问题时，必须在当前任务结束前向用户提出 `[KNOWLEDGE UPDATE PROPOSAL]`，明确标注目标文件（`knowledge/priors.yaml` 或 `harness/knowledge.yaml`）、section、条目内容。用户确认后写入，拒绝则不写入但记录到报告中。
