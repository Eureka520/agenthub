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

> **欢迎提交 [Issue](https://github.com/Eureka520/agenthub/issues) 反馈 BUG 和建议。**

---

## 核心价值

AgentHub 解决三个问题：

**1. Agent 怎么用得到远程算力？**
通过 MCP 协议安全操控远程 GPU 机器，无需暴露 SSH —— Agent 自动发现工具，直接创建容器、执行命令、管理 GPU。

**2. Agent 怎么完成复杂长链路任务？**
提测文档扔进去，自动解析为 TestPlan、按 DAG 依赖编排执行、GPU 智能选择、网络故障自动切换、断点恢复 —— 不是跑一个命令，而是跑完一整套流程。

**3. Agent 怎么越用越聪明？**
每次执行中积累的经验（最佳做法、故障修复）持久化到知识库。下次遇到同类操作，Agent 直接按最优路径执行而非现场试错。

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
│   harness (TestPlan → DAG 编排 → 执行 → 报告)              │
│   knowledge/priors.yaml (先验知识 — 越用越聪明)              │
│   knowledge.yaml (异常修复经验 — 自动 pattern 匹配)          │
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

### 智能测试执行 (harness)

| 能力 | 说明 |
|------|------|
| 文档解析 | .md 提测文档 → 结构化 TestPlan（Pydantic 验证） |
| DAG 编排 | 按依赖关系构建 LangGraph，逐步执行 |
| GPU 智选 | 自动选空闲 GPU，锁定 CUDA_VISIBLE_DEVICES |
| 网络容错 | 超时自动切代理/镜像源，fire-and-poll 避免长操作断开 |
| 三级错误处理 | L1 自动修复、L2 尝试一次、L3 停止保留现场 |
| 断点恢复 | Checkpoint 机制，失败后可 resume |
| 降级模式 | harness 编排不可用时，Agent 手动按 TestPlan 逐步执行，约束不降级 |
| 报告输出 | 每次必产出报告（执行模式、问题解决记录、知识更新） |

### 知识积累系统

| 层级 | 文件 | 定位 |
|------|------|------|
| 先验知识 | `knowledge/priors.yaml` | "优先这么做" —— Agent 执行前查阅的操作手册 |
| 异常经验 | `harness/knowledge.yaml` | "出错后这么救" —— stderr pattern 匹配自动修复 |

**更新闭环**：Agent 发现新经验 → 总结 Proposal → 用户确认 → 写入知识库 → 下次直接用。

---

## 快速开始

```bash
git clone https://github.com/Eureka520/agenthub.git
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
      "type": "sse",
      "url": "http://<目标机器IP>:9100/sse"
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
├── harness/         # 测试编排引擎（解析→执行→报告）
├── knowledge/       # 先验知识库（越用越聪明）
└── docs/            # 架构文档、API、设计 spec
```

---

## 许可证

[Apache 2.0](LICENSE) © 2026 Eureka520

