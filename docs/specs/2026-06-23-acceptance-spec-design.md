# AgentHub AcceptanceSpec 设计 Spec

## 概述

本 spec 定义 AgentHub Phase 1（基础工程治理）中的 **AcceptanceSpec（验收规格）** 机制：在任务执行**之前**显式声明"什么算完成"，并在执行过程中以**阶段门禁**方式强制校验，避免 agent 在异构 GPU/硬件/深度学习/大模型任务里"自我感觉良好地完成了"。

定位：与 TestPlan 解耦的独立 YAML 制品。TestPlan 描述"做什么"，AcceptanceSpec 描述"做成什么样算完"。两者由 harness 在执行前分别生成、分别由用户 CLI 确认、分别落盘。

本 spec **不**覆盖：
- Phase 2 的 Verifier Agent（带工具调用的深度根因分析）
- EvidenceManifest 全量证据图谱
- ProgressLog 事件流

---

## 1. 目标与非目标

### 1.1 目标

1. 在任务启动前，把"完成判定"从 agent 的隐式判断变成显式可审计的 YAML 规约
2. 每个 stage 结束都触发验收检查，不通过 → 走错误处理流程，不允许跳过
3. 任务结束有可读的"验收结论"段落落入最终报告
4. 设计与 task_type 解耦：当前涵盖 GPU 推理 / 训练 / 数据分析 / Issue 复现 / 算子 bench 等，扩展只需新增 task_type 模板

### 1.2 非目标

- 不替代 TestPlan，不与 TestPlan 合并
- 不引入新的 agent（Drafter 是 DAG 中的一个 LLM 节点，非独立 Verifier Agent）
- 不做跨任务的对比基线管理（留给后续 Benchmark 子系统）

---

## 2. AcceptanceSpec Schema

### 2.1 Hybrid 结构

通用骨架（apiVersion / kind / task_type / acceptance_mode / stages） + 任务类型特化的 `task_assertions` 段，参考 K8s `kind + spec` 模式。

```yaml
apiVersion: agenthub/v1
kind: AcceptanceSpec
task_type: inference          # seed: inference | training | data_analysis | issue_repro | kernel_bench | ...（可扩展枚举）
acceptance_mode: strict       # strict | advisory；advisory 仅记录不阻断

stages:
  - name: install
    exit_criteria: "依赖安装成功，关键包可 import"
    artifacts:
      - path: logs/install.log
        required: true
    retry:
      max_attempts: 1         # 可选，默认 1

  - name: service_start
    exit_criteria: "health_check 返回 200 且服务进程存活 ≥ 30s"
    artifacts:
      - path: logs/service.log
        required: true

  - name: test_run
    exit_criteria: "推理流程结束且无 L3 错误"
    artifacts:
      - path: outputs/results.tar.gz
        required: true
      - path: outputs/metrics.json
        required: false
    metrics:
      - name: images_processed
        expect: ">= 1355"
      - name: failure_rate
        expect: "<= 0.001"

# 跨 stage 的业务级断言，在 final_acceptance 节点统一校验
task_assertions:
  - name: paddle_vs_vllm_diff
    expect: "<= 0.005"
  - name: coverage
    expect: "== 1.0"
```

### 2.2 字段语义

| 字段 | 必填 | 说明 |
|------|------|------|
| `task_type` | ✓ | 可扩展枚举；驱动 drafter 选模板，不影响 harness 代码 |
| `acceptance_mode` | ✓ | `strict` 不通过即抛 ACCEPTANCE_FAILED；`advisory` 仅记录到报告 |
| `stages[].name` | ✓ | 必须与 TestPlan 的 stage 名一一对应 |
| `stages[].exit_criteria` | ✓ | 自然语言；LLM + 规则混合判定（详见 §4.2） |
| `stages[].artifacts[].required` | - | 默认 false；true 表示文件不存在直接 fail |
| `stages[].metrics[].expect` | - | 表达式：`>=`/`<=`/`==`/`!=`/`<`/`>` + 数值或字符串 |
| `stages[].retry.max_attempts` | - | 默认 1；为局部逃生口 |
| `task_assertions` | - | 跨 stage 的最终业务断言 |

### 2.3 task_type 扩展性

当前 stage 骨架（install / service_start / test_run）对 GPU/硬件/DL/LLM 任务的覆盖：

| 任务类型 | install | service_start | test_run | 说明 |
|----------|---------|---------------|----------|------|
| LLM 推理（vLLM/Paddle） | 装依赖 | 起 server | 跑请求/对比 | 完整三段 |
| LLM 训练 | 装依赖+下载权重 | — | 跑训练步 | service_start 可省 |
| CV/小模型推理 | 装依赖 | 加载模型 | 推图 | 完整三段 |
| 数据分析 | 装依赖 | — | 跑脚本 | service_start 可省 |
| Issue 复现 | 装依赖+复现环境 | 可选 | 复现脚本 | — |
| 算子 / Kernel Bench | 编译/装依赖 | — | 跑 bench | — |
| 分布式训练 | 装依赖+起 worker | rendezvous（可改名 cluster_ready） | 跑训练 | stage 名跟随 TestPlan |

**关键**：stages 不是写死的三段，AcceptanceSpec 严格按 TestPlan 实际生成的 stage 列表对齐。新任务类型只需在 `priors.yaml` / drafter prompt 里追加一个 task_type 模板，**无需改 harness 代码**。

---

## 3. 生成流程：Drafter Node

### 3.1 时序

```
用户输入需求
  → TestPlan drafter → CLI 确认 TestPlan
  → AcceptanceSpec drafter（新增节点）
      ① 读已确认的 TestPlan，拿到 stage 列表
      ② 检索 priors.yaml 中同 task_type 的历史 spec / 经验
      ③ LLM 起草 acceptance_spec.yaml
      ④ 写入 outputs/acceptance_spec.yaml
  → CLI 交互：[A]ccept / [E]dit / [R]egenerate
  → 用户确认 → freeze → 进入正式执行 DAG
```

### 3.2 为什么不和 TestPlan 合并生成

- **心智模型不同**：TestPlan 是执行步骤，AcceptanceSpec 是验收契约
- **可独立编辑**：用户可只调验收阈值不改执行脚本
- **可独立复用**：同一类任务的验收模板可跨项目共享
- **生成顺序约束**：AcceptanceSpec 必须读到已确认的 TestPlan stage 列表才能生成，不可同时

### 3.3 Drafter 输入

- 已确认的 TestPlan（stage 列表 + 任务描述）
- `priors.yaml` 中匹配 `task_type` 的若干历史 spec 片段
- 任务上下文（用户原始需求、目标硬件、目标模型 / 框架版本）

---

## 4. 执行时强制：Stage-Gate 模型

### 4.1 集成点

| 模块 | 改动 |
|------|------|
| `harness/orchestrator/state.py` | 新增 `acceptance_spec`、`acceptance_results` 字段到 `HarnessState` |
| `harness/orchestrator/nodes.py` | 每个 stage 节点末尾插入 `_check_acceptance(state, stage)`；DAG 末尾新增 `final_acceptance` 节点 |
| `harness/error_handler.py` | 新增 `ACCEPTANCE_FAILED` pattern，默认 `level=L2, solution=rerun_stage` |
| `harness/templates/report.md` | 新增"验收结论"段落 |

### 4.2 _check_acceptance 判定逻辑

按以下顺序判断当前 stage 是否通过：

1. **artifacts.required**：所有 `required: true` 的文件必须存在且非空 → 否则 fail
2. **metrics**：若 stage 写出 `metrics.json`，按 `expect` 表达式逐条校验 → 任一不满足 fail
3. **exit_criteria**：自然语言断言，LLM 读取 stage log + artifacts 摘要做最终判定 → fail/pass

三者全过才算 stage 通过；任一失败 → 抛 `ACCEPTANCE_FAILED`。

### 4.3 metric 来源策略：约定优先 + LLM 兜底

- **首选**：每个 stage 的执行脚本按约定写出 `outputs/metrics.json`
- **兜底**：未写 metrics.json 时，LLM 从 log + artifacts 中抽取，写入 `acceptance_results` 并标记 `source: llm_extracted`

兜底结果在报告中显式标注，提示用户后续在脚本中显式输出。

### 4.4 final_acceptance 节点

DAG 末尾节点：
- 校验 `task_assertions` 中所有跨 stage 业务断言
- 汇总各 stage 的 `acceptance_results`
- 写入报告"验收结论"段落（PASS/FAIL + 各项明细 + 失败原因）

### 4.5 advisory 模式

`acceptance_mode: advisory` 时：
- `_check_acceptance` 不抛错，仅写 `acceptance_results`
- 报告中显著标注"⚠ 本任务运行在 advisory 模式，验收失败未阻断执行"
- 用作探索性任务 / 历史任务回放的逃生口

---

## 5. ACCEPTANCE_FAILED 错误处理

### 5.1 触发场景（统一错误码）

| # | 触发 | 示例 |
|---|------|------|
| 1 | exit_criteria 不满足 | stage 退出码非 0 / 关键 log 模式未出现 |
| 2 | required artifact 缺失 | `results.tar.gz` 不存在或为空 |
| 3 | metric 越界 | `images_processed=1200`，要求 `>=1355` |

### 5.2 默认级别：L2（不是 L3）

- 大多验收失败和现有 L2 错误同类（OOM 抖动、超时、网络瞬断、metric 临界）
- 直接 L3 会让 agent 过早放弃；盲目 L1 又不合适——验收失败的"修复"不是改代码

### 5.3 重试策略：诊断 + 单次重试

```
ACCEPTANCE_FAILED 触发
  ↓
Step A: 轻量诊断（LLM 单次调用，内联在 error_handler）
  读 stage log / artifacts / metrics，分类：
    (a) 偶发/环境类（OOM / 超时 / 网络）        → 进 Step B
    (b) 确定性失败（metric 稳定低于阈值 / 文件未生成） → 直接升 L3
    (c) 配置/参数类（batch_size 过大等）        → 给出建议，升 L3 让用户介入
  ↓
Step B: 执行 rerun_stage（仅 (a) 走到这里）
  - 重新执行该 stage 节点
  - 再次跑 _check_acceptance
  - 仍失败 → 升 L3，不再重试
```

### 5.4 为什么只重试一次

- 验收失败大多是**确定性的**（metric 不达标重试 100 次也不达标），多次重试只浪费 GPU
- 偶发问题一次重试足以验证（再失败说明非偶发）
- 用户可通过 `stages[].retry.max_attempts` 局部覆盖

### 5.5 与 Phase 2 Verifier Agent 的衔接

Step A 的诊断 Phase 1 是 LLM 单次调用（轻量）；Phase 2 升级为独立 Verifier Agent，带工具调用（grep log、查历史相似案例、读 priors）做深度根因分析。Phase 1 先打通链路。

---

## 6. 与现有模块的集成清单

| 文件 | 改动类型 | 摘要 |
|------|----------|------|
| `harness/orchestrator/state.py` | 扩展 | `HarnessState` 新增 `acceptance_spec: dict`、`acceptance_results: dict` |
| `harness/orchestrator/nodes.py` | 新增 + 改造 | 新增 `acceptance_drafter` 节点、`final_acceptance` 节点；每个 stage 节点末尾调 `_check_acceptance` |
| `harness/error_handler.py` | 新增模式 | `ACCEPTANCE_FAILED` → `ErrorMatch(level="L2", solution="rerun_stage")` |
| `harness/knowledge.yaml` | 不动 | AcceptanceSpec 不直接修改此文件 |
| `harness/templates/report.md` | 扩展 | 新增"## 验收结论"段落 |
| `harness/schemas/` | 新增 | `acceptance_spec.schema.json` 用于校验 yaml |
| `knowledge/priors.yaml` | 扩展 | 新增 `acceptance_templates` section，按 task_type 存模板片段 |

---

## 7. Phase 1 不做的事（显式 Deferral）

| 项 | 推迟到 | 原因 |
|----|--------|------|
| Verifier Agent（独立 agent + 工具链） | Phase 2 | 先用 LLM 单次调用打通链路，避免一上来就引入新 agent |
| EvidenceManifest（产物溯源图） | Phase 2 | 当前 artifacts 数组够用 |
| 完整 ProgressLog 事件流 | Phase 3 | 当前 stage_results + report 足够 |
| 跨任务基线对比 | 后续 Benchmark 子系统 | AcceptanceSpec 是单任务契约，不承担基线 |
| 自动从历史失败学习更新 spec 模板 | Phase 2 | 先沉淀人工编辑的模板到 priors.yaml |

---

## 8. 验收（本 spec 自身）

落地后应满足：

- [ ] 任意新任务运行后，`outputs/acceptance_spec.yaml` 存在且与 TestPlan stage 一一对应
- [ ] 报告中"验收结论"段落出现 PASS/FAIL 明细
- [ ] 故意制造 metric 越界的回归测试能正确触发 `ACCEPTANCE_FAILED(L2)` → 诊断 → 单次重试 → 升 L3
- [ ] `acceptance_mode: advisory` 模式下验收失败不阻断且报告显著标注
- [ ] 新增一个 task_type（如 `kernel_bench`）只需在 `priors.yaml` 加模板，harness 代码零改动

---

## 9. 后续行动

本 spec 确认后，下一步交付物：
1. 用 `writing-plans` skill 产出实现计划（拆分到 PR 粒度）
2. 在 `priors.yaml` 中先补 inference / training / data_analysis / issue_repro 四个 task_type 的 acceptance 模板
3. 实现 schemas/acceptance_spec.schema.json + drafter 节点 + stage hook + final_acceptance 节点
