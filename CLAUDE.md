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

**禁止绕过**：agent 不得以"快速分析"、"先探索一下"、"简单验证"、"只是看一下环境"等理由跳过此流程。探索性操作同样必须在 TestPlan stage 中声明并通过门禁后执行。

---

### ▶ CHECKPOINT-1：任务识别（收到任务后，执行任何 MCP 调用前）

收到涉及远端执行的任务后，**必须先输出以下自检块**，再做任何其他事情：

```
# [CHECKPOINT-1: TASK INTAKE]
- 任务涉及 MCP 远端执行？ [YES/NO]
- 如果 YES → 进入 harness 流程，无例外
- 已读 knowledge/priors.yaml？ [YES — 匹配条目: ...]
- 已读 harness/knowledge.yaml？ [YES — 相关 pattern: ...]
- task_type: [inference/training/issue_repro/data_analysis/...]
```

**此 checkpoint 强制的规则**：
1. 执行任何操作前，先查阅 `knowledge/priors.yaml` 获取相关领域的推荐做法并遵循。priors 中有明确 preferred 的，优先使用而非现场发挥。
2. 遇到错误先查 `harness/knowledge.yaml`，匹配已知模式则按方案处理。

---

### ▶ CHECKPOINT-2：计划确认（生成 TestPlan + AcceptanceSpec，等待用户确认）

**必须先生成 TestPlan** 并展示给用户，用户 CLI 确认后才能继续。禁止跳过 TestPlan 直接调用 MCP 工具执行。

TestPlan 用户确认通过后，**必须生成 AcceptanceSpec** 并向用户展示验收标准（required artifacts、metrics 阈值、exit_criteria、acceptance_mode）。用户 CLI 确认（[A]ccept/[E]dit/[R]egenerate）后冻结。禁止跳过 AcceptanceSpec 确认直接执行。

用户确认后，**必须输出以下自检块**：

```
# [CHECKPOINT-2: PLAN CONFIRMED]
- TestPlan 已展示并确认？ [YES]
- AcceptanceSpec 已展示并确认？ [YES]
- acceptance_mode: [strict/advisory]
- stages: [列出所有 stage id]
```

**此 checkpoint 强制的规则**：
3. 必须通过 harness 编排引擎逐步执行，不能跳步骤。
4. 无对应 MCP 节点的硬件标记 skip，不模拟结果。
5. install/service_start/test_run 禁止在宿主机直接执行，必须在 docker 或 venv 中。生成 TestPlan 时注意正确归类 stage type。

---

### ▶ CHECKPOINT-3：门禁初始化（AcceptanceSpec 确认后的紧接着下一条回复）

此回复中**禁止包含任何 MCP container_exec / shell_exec 调用**，只做以下三件事：

1. 创建 `outputs/` 目录及每个 stage 的子目录
2. 写入 `outputs/acceptance_spec.yaml`（冻结版）
3. 输出 HarnessState 代码块，格式**必须以下面这行开头**（逐字匹配）：

```
# === HarnessState Initialized ===
task: [任务描述]
execution_mode: manual_orchestration
stages:
  - id: [stage1], status: pending
  - id: [stage2], status: pending
  - ...
current_stage: null
progress_log: outputs/progress_log.jsonl
priors_applied: [本任务将用到的 priors 条目列表]
```

**门禁判定规则**：
- 当前会话中如果不存在已输出的 `# === HarnessState Initialized ===` 标记，则后续任何 MCP `container_exec` / `shell_exec` 调用均为 **L3 违规**
- 输出该标记的回复中混入 MCP 执行调用，同样视为 **L3 违规**
- L3 后果：已产出的结果全部作废，必须从头重新执行 harness 流程

**自查提示**：在生成任何 MCP 执行调用前，停下来确认——"我这个会话中是否已经输出过 `# === HarnessState Initialized ===`？"如果没有，立即停止并先完成初始化。

---

### ▶ CHECKPOINT-4：Stage 完成（每个 stage 执行结束后立刻）

每个 stage 结束后，**必须输出以下自检块**，再进入下一个 stage：

```
# [CHECKPOINT-4: STAGE COMPLETE — {stage_id}]
- status: [ok/fail/skip]
- duration: [X]s
- artifacts: [产出文件列表]
- metrics: {key: value} 或 N/A
- acceptance_check: [PASS/FAIL — 理由]
- errors: [列出遇到的错误] 或 none
- knowledge.yaml_match_used: [使用了哪个 pattern] 或 none
- new_discovery: [YES: 简述 / NO]
```

**此 checkpoint 强制的规则**：
6. 执行任务时，每个 stage 结束后执行 evidence 收集（扫描 `outputs/<stage>/` 生成 `manifest.json`）→ acceptance 检查（比对 `acceptance_spec.yaml` 中的 artifacts/metrics/exit_criteria）。不可跳过或绕过。
7. `ACCEPTANCE_FAILED` 为 L2 错误：先诊断（读 manifest + log 分类偶发/确定性/配置类），偶发类单次重试，确定性/配置类直接升 L3。不要盲目重试。
8. 环境创建后不自动删除，标记保留信息供再进入。
9. 网络问题按 `harness/config.yaml` 代理策略处理。
10. 未知错误不猜测解决方案，记录完整 stderr 并停止。
11. 服务类操作必须后台启动 + 健康检查确认就绪。
12. 用户教你解决测试错误时，必须将 pattern + solution 写入 `harness/knowledge.yaml`。
13. 执行脚本可选写 `outputs/<stage>/manifest.hints.json` 给关键产物打 label/description；可选写 `outputs/<stage>/metrics.json` 提供结构化指标。未写时 harness 自动扫描 + LLM 兜底提取。

---

### ▶ CHECKPOINT-5：任务结束（最终报告）

任务结束时（无论成功或中途失败），**必须输出以下完整报告**：

```
# [CHECKPOINT-5: TASK COMPLETE]

## 验收结论
| Stage | Result | Detail |
|-------|--------|--------|
| ...   | PASS/FAIL | ... |

## 产物清单
| Path | Size | SHA256(前12位) | Role |
|------|------|----------------|------|
| ...  | ...  | ...            | required/auxiliary |

## 关键事件时间线
| Time | Stage | Event | Summary |
|------|-------|-------|---------|
| ...  | ...   | ...   | ...     |

## 知识沉淀
[KNOWLEDGE UPDATE PROPOSAL]（如有新发现）
- target: [knowledge/priors.yaml 或 harness/knowledge.yaml]
- section: [...]
- content: [...]
（如无新发现，写"无新增"）

## 环境保留
- 容器: `docker exec -it {name} bash`
- 再进入方式: [...]

## 执行模式
- mode: [graph_invoke / manual_orchestration]
- degradation_reason: [如有]
```

**此 checkpoint 强制的规则**：
14. 最终报告必须包含三段：**验收结论**（PASS/FAIL 明细）/ **产物清单**（path/size/sha256/role）/ **关键事件时间线**（从 `progress_log.jsonl` 渲染）。缺任一段视为报告不完整。
15. **Verifier 验证**：harness 在 `final_acceptance` 之后会自动运行 Verifier（独立 `claude -p` 子进程，只读工具 Read/Glob/Grep）。其结果写入 `outputs/verifier_verdict.json` 与最终报告。Worker 不得读取或修改 `verifier_verdict`，也不得绕过 Verifier。
16. 当你通过尝试发现了更优的操作方式或解决了新问题时，必须在报告中提出 `[KNOWLEDGE UPDATE PROPOSAL]`，明确标注目标文件、section、条目内容。用户确认后写入，拒绝则不写入但记录到报告中。

---

### 补充规则（贯穿全流程）

17. `acceptance_mode: advisory` 是显式逃生口——验收失败只记录不阻断，但报告中必须显著标注。仅用于探索性任务或历史回放，正式任务必须 `strict`。
18. 新任务类型只需在 `knowledge/priors.yaml` 的 `acceptance_templates` section 添加 task_type 模板，不要修改 harness 框架代码（`acceptance.py` / `evidence.py` / `progress_log.py` / `graph.py`）。
19. 手动编排模式下 agent 必须维护 HarnessState dict（记录每个 stage 的 status/duration/errors/commands_run），所有约束规则同样生效，不可降低标准。

See `harness/skill.md` for full harness specification.
See `docs/specs/2026-06-23-acceptance-spec-design.md` for full design specification.
