# AgentHub — 让 AI Agent 越用越聪明的研发基础设施

[English](README.en.md) | 中文

```
   █████╗ ██╗  ██╗██╗   ██╗██████╗
  ██╔══██╗██║  ██║██║   ██║██╔══██╗
  ███████║███████║██║   ██║██████╔╝
  ██╔══██║██╔══██║██║   ██║██╔══██╗
  ██║  ██║██║  ██║╚██████╔╝██████╔╝
  ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝
```

> **欢迎提交 [Issue](https://github.com/lqliu7/agenthub/issues) 反馈 BUG 和建议。**

---

## 核心价值

AgentHub 面向 GPU / 深度学习 / 大模型这类长链路研发场景，解决四个问题：

### 1. Agent 怎么用得到远程算力？

通过 MCP 协议安全操控远程 GPU 机器，无需暴露 SSH —— Agent 自动发现工具，直接创建容器、执行命令、管理 GPU。

### 2. GPU 时代的研发工作流怎么重塑？

模型评测、训练复现、算子调优、推理压测等 GPU 场景长期依赖人工串联环境、算力、执行与排障流程，效率低且难以复用。AgentHub 将任务描述自动转化为可执行 DAG，完成环境准备、GPU 调度、任务推进、故障恢复与结果验收，实现从人工驱动到 AI 驱动、可复用、可审计工作流的转变，让工程师聚焦决策与创新而非重复操作。

### 3. 长链路怎么不跑偏、可靠交付而非"自我感觉完成"？

现有 Agent 在长链路任务中常**执行偏移、自证清白**——目标随上下文漂移、日志看似 OK 实则产物缺失。AgentHub 用 **harness** 把长链路装进硬约束：AcceptanceSpec 冻结验收契约，DAG 逐 stage 门禁，产物指纹与决策全程留痕；并引入独立 **Verifier 子 Agent**——物理隔离的只读裁判进程，对 Worker 产物做二次校验，从机制上杜绝"自己判自己合格"。长链路任务从黑盒漂移变为**全链路约束、可验证、可追溯**的可靠交付。

### 4. Agent 怎么越用越聪明？

每次执行中积累的经验（最佳做法、故障修复、验收模板）持久化到知识库。下次遇到同类操作，Agent 直接按最优路径执行而非现场试错。

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                        用户层                                │
│   手机/平板/电脑 ──WebSocket──▶ AgentHub Server (:8310)     │
│   本地终端 ────Unix Socket────▶      ▲                      │
│                                       │ PTY 管理            │
│                           Claude Code / Codex               │
└───────────────────────────────┬─────────────────────────────┘
                                │ MCP 协议
┌───────────────────────────────▼─────────────────────────────┐
│                     远程算力层                                │
│   ahub-node (A100/T4/L20/H20...) ──▶ Docker + GPU          │
│   7 个 MCP 工具 | 三级安全管控 | 并发支持                    │
└───────────────────────────────┬─────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────┐
│                      智能执行层                               │
│   harness (TestPlan → DAG 推进 → 验收门禁 → Verifier → 报告)│
│   工作流三件套：定义完成标准 → 采集执行证据 → 审计决策过程    │
│   knowledge (先验知识 + 异常经验 — 越用越聪明)               │
└─────────────────────────────────────────────────────────────┘
```

---

## 功能矩阵

### 多端协同终端

| 能力 | 说明 |
|------|------|
| 实时多端同步 | 手机、平板、电脑同时接入同一个 Agent 会话，共享 PTY |
| 持久会话 | 所有端断开，Agent 后台继续工作，随时重连 |
| 真实终端 | 颜色、交互、鼠标，和本地无区别 |
| 文件浏览器 | Web 端浏览服务器文件，预览代码/图片 |
| 文件上传 | 拖拽/粘贴/按钮，路径自动填入终端 |
| 历史恢复 | 自动读取 Claude Code / Codex 历史会话 |
| 外观定制 | 9 种 UI 风格、深浅配色、6 套图标 |

### 远程算力管控 (ahub-node)

| MCP 工具 | 功能 |
|----------|------|
| `shell_exec` | 宿主机执行命令 |
| `container_exec` | 容器内执行命令 |
| `container_manage` | 创建/列表/停止/删除容器 |
| `file_read` / `file_write` | 读写文件（宿主机或容器） |
| `system_info` | CPU/内存/GPU/磁盘/容器全景状态 |
| `transfer_file` | 宿主机与容器间传输文件 |

**安全模型**：命令三级管控（free / confirm / blocked），危险操作需要确认 token，高危操作直接拦截。

### GPU 工作流重塑 (harness)

| 能力 | 说明 |
|------|------|
| 文档解析 | .md 任务文档（评测/训练/调优/压测…）→ 结构化 TestPlan（Pydantic 验证） |
| DAG 推进 | 按依赖关系构建 LangGraph，逐步推进长链路任务 |
| GPU 智选 | 自动选空闲 GPU，锁定 CUDA_VISIBLE_DEVICES |
| 网络容错 | 超时自动切代理/镜像源，fire-and-poll 避免长操作断开 |
| 三级错误处理 | L1 自动修复、L2 尝试一次、L3 停止保留现场 |
| 断点恢复 | Checkpoint 机制，失败后可 resume |
| 降级模式 | harness 不可用时，Agent 手动按 TestPlan 逐步执行，约束不降级 |
| 可交互验收标准 | Agent 不再自行判断"做完了没"——执行前与用户协商验收契约（AcceptanceSpec），冻结后作为硬约束逐 stage 门禁校验，确保长链路任务每一步都可靠交付 |
| 产物证据链 | 每个 stage 自动登记产物指纹（path/size/sha256），机器校验 + 人类审计双可用，Agent "说做了"必须有证据证明 |
| 决策可追溯 | 关键决策点（验收判定、错误诊断、重试触发）结构化记录，长任务不再黑盒——失败时能精确定位哪一步、因为什么、做了什么决策 |
| 独立验证 (Verifier) | 物理隔离的二次裁判——独立 `claude -p` 子进程仅持只读工具，无法篡改产物，杜绝 Worker 自证清白 |
| 报告输出 | 每次必产出报告（验收结论、产物清单、事件时间线、问题解决记录） |

### 知识积累系统

| 层级 | 文件 | 定位 |
|------|------|------|
| 先验知识 | `knowledge/priors.yaml` | "优先这么做" —— Agent 执行前查阅的操作手册 |
| 异常经验 | `harness/knowledge.yaml` | "出错后这么救" —— stderr pattern 匹配自动修复 |
| 验收模板 | `priors.yaml: acceptance_templates` | "做成什么样算完" —— 按任务类型积累验收标准，新任务自动继承历史经验 |

**更新闭环**：Agent 发现新经验 → 总结 Proposal → 用户确认 → 写入知识库 → 下次直接用。

---

## 快速开始

```bash
git clone https://github.com/lqliu7/agenthub.git
cd agenthub
bash install.sh        # 交互式安装，自动检测环境
agenthub start         # 启动服务
```

浏览器打开 `http://<服务器IP>:8310`，或在终端运行 `agenthub` 弹出管理菜单。

### 部署远程算力节点

```bash
# 目标 GPU 机器上（需 Python 3.10+）
pip install mcp pyyaml
python ahub-node/server.py
```

AgentHub 侧配置 `~/.claude/.mcp.json`：

```json
{
  "mcpServers": {
    "node-A100": {
      "type": "http",
      "url": "http://<目标机器IP>:9100/mcp",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

---

## 常用命令

```bash
agenthub start          # 启动（守护进程，崩溃自重启）
agenthub stop           # 停止
agenthub restart        # 完整重启
agenthub reload         # 热重载（不断会话）
agenthub update         # 拉取最新 + 自动重启
agenthub status         # 服务状态
agenthub                # 可视化菜单
agenthub attach <名称>  # 进入指定会话
```

会话内 **`Ctrl+]`** 退回菜单，不终止 Agent。

---

## 项目结构

```
agenthub/
├── server/          # Node.js 后端（PTY 管理、WebSocket、REST API）
├── client/          # Vue 3 前端（xterm.js 终端、文件浏览器）
├── ahub-node/       # MCP Server（远程算力节点）
├── harness/         # GPU 工作流引擎（解析→推进→验收→验证→报告）
├── knowledge/       # 先验知识库（越用越聪明）
└── docs/            # 架构文档、API、设计 spec
```

---

## 许可证

[Apache 2.0](LICENSE) © 2026 lqliu7

