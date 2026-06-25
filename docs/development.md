# 开发指南 / Development Guide

[中文](#中文) | [English](#english)

---

## 中文

### 获取代码

```bash
git clone https://github.com/lqliu7/agenthub.git
cd agenthub
```

### 开发环境启动

#### 后端（热重载）

```bash
cd server
RC_USER=admin RC_PASS=yourpassword PORT=8310 node --watch index.js
```

#### 前端（Vite dev server）

```bash
cd client
npm run dev
# 访问 http://localhost:5173，自动代理 API 和 WS 到 localhost:8310
```

### 目录结构

```
agenthub/
├── server/
│   ├── index.js        # HTTP + WS 入口
│   ├── auth.js         # Token 认证 + 本地 token
│   ├── pty-manager.js  # PTY 会话池（核心）
│   └── history.js      # Agent history reader
├── client/
│   └── src/
│       ├── App.vue          # 主组件：认证/路由/WS/会话管理
│       ├── router.js        # Hash 路由
│       ├── settings.js      # 全局设置 + 主题定义
│       ├── themes.js        # xterm.js 终端配色
│       ├── i18n.js          # 中英文字典
│       └── components/
│           ├── AppIcon.vue          # 统一 SVG 图标系统
│           ├── Terminal.vue         # xterm.js 渲染（纯展示）
│           ├── SymbolBar.vue        # CC/SH 双模式快捷键栏
│           ├── ConversationList.vue # 首页会话列表
│           ├── NewConversation.vue  # 新建/恢复对话
│           ├── SettingsPage.vue     # 设置页
│           ├── LogViewer.vue        # 日志查看
│           └── HelpPage.vue         # 内嵌文档阅读
├── docs/               # 双语文档
├── agenthub            # 统一 CLI 入口
├── ahub-tui             # 交互式 TUI
├── ahub-server          # 守护进程管理（bash）
└── install.sh          # 一键部署脚本
```

### 添加颜色主题

1. `client/src/themes.js` 添加 xterm 配色
2. `client/src/settings.js` 的 `COLOR_THEMES` 数组添加主题条目
3. `client/src/App.vue` 全局 CSS 添加 CSS 变量

### 添加图标风格

1. `client/src/settings.js` 的 `ICON_STYLES` 添加风格条目
2. `client/src/components/AppIcon.vue` 添加对应 SVG 形态
3. `client/src/i18n.js` 添加中英文说明

### 添加 WS 消息类型

1. `server/pty-manager.js` 的 `handleMessage` switch 添加 case
2. `client/src/App.vue` 的 `connectEntryWS` `onmessage` 处理
3. 更新 `docs/api.md`

### 代码规范

- Vue 组件：`<script setup>` + Composition API
- CSS：优先用 `var(--neon)` 等 CSS 变量，跟随主题
- 错误处理：WS/PTY 操作用 try/catch，不向用户暴露原始错误

### 构建与发布

```bash
cd client && npm run build
cd ../server && RC_USER=admin RC_PASS=yourpassword PORT=8310 node index.js
```

---

## English

### Get the Code

```bash
git clone https://github.com/lqliu7/agenthub.git
cd agenthub
```

### Dev Environment

#### Backend (hot reload)

```bash
cd server
RC_USER=admin RC_PASS=yourpassword PORT=8310 node --watch index.js
```

#### Frontend (Vite dev server)

```bash
cd client
npm run dev
# Open http://localhost:5173, API and WS proxied to localhost:8310
```

### Project Structure

```
agenthub/
├── server/
│   ├── index.js        # HTTP + WS entry point
│   ├── auth.js         # Token auth + local token
│   ├── pty-manager.js  # PTY session pool (core)
│   └── history.js      # Agent history reader
├── client/
│   └── src/
│       ├── App.vue          # Main: auth/routing/WS/session mgmt
│       ├── router.js        # Hash router
│       ├── settings.js      # Global settings + themes
│       ├── themes.js        # xterm.js color schemes
│       ├── i18n.js          # zh/en dictionary
│       └── components/
│           ├── AppIcon.vue          # Unified SVG icon system
│           ├── Terminal.vue         # xterm.js renderer (pure display)
│           ├── SymbolBar.vue        # CC/SH dual-mode symbol bar
│           ├── ConversationList.vue # Home session list
│           ├── NewConversation.vue  # New/resume conversation
│           ├── SettingsPage.vue     # Settings
│           ├── LogViewer.vue        # Log viewer
│           └── HelpPage.vue         # Embedded docs reader
├── docs/               # Bilingual documentation
├── agenthub            # Unified CLI entry
├── ahub-tui             # Interactive TUI
├── ahub-server          # Daemon manager (bash)
└── install.sh          # One-click deploy script
```

### Adding a Color Theme

1. Add xterm color scheme in `client/src/themes.js`
2. Add an entry to `COLOR_THEMES` in `client/src/settings.js`
3. Add CSS variables in the global `<style>` block in `client/src/App.vue`

### Adding an Icon Style

1. Add an entry to `ICON_STYLES` in `client/src/settings.js`
2. Add the matching SVG shapes in `client/src/components/AppIcon.vue`
3. Add zh/en descriptions in `client/src/i18n.js`

### Adding a WS Message Type

1. Add `case` in `handleMessage` switch in `server/pty-manager.js`
2. Handle in `connectEntryWS` `onmessage` in `client/src/App.vue`
3. Update `docs/api.md`

### Code Style

- Vue: `<script setup>` + Composition API
- CSS: prefer `var(--neon)` CSS variables, theme-aware
- Error handling: wrap WS/PTY ops in try/catch, don't expose raw errors to users

### Build & Run

```bash
cd client && npm run build
cd ../server && RC_USER=admin RC_PASS=yourpassword PORT=8310 node index.js
```

---

## License / 许可证

Apache 2.0 — see [LICENSE](../LICENSE)
