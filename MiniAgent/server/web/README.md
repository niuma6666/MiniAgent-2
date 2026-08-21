# MiniAgent Web 前端（server/web）

P2 的 React 仪表盘：Vite + React 18 + TypeScript + zustand + react-grid-layout。
事件协议见 `server/PROTOCOL.md`（v2）。

## 目录结构

```
server/web/
├── src/
│   ├── main.tsx               # 入口
│   ├── App.tsx                # 三栏布局：组件面板 + 画布 + 属性面板
│   ├── store.ts               # agent 会话状态（单一事件源 items 列表）
│   ├── dashboardStore.ts      # 画布布局/组件实例 + localStorage 持久化
│   ├── widgets.tsx            # 组件注册表（新增组件在此登记）
│   ├── lib/
│   │   ├── ws.ts              # WS 客户端（单例连接/重连/hello）
│   │   └── markdown.ts        # marked 渲染 + FINAL_ANSWER 剥离
│   └── components/
│       ├── Dashboard.tsx      # react-grid-layout 画布
│       ├── Palette.tsx        # 组件面板 + 导出/导入
│       ├── Properties.tsx     # 属性面板
│       ├── ChatPanel.tsx      # 对话（流式/markdown/确认弹窗/新会话）
│       ├── ToolLogPanel.tsx   # 工具日志
│       └── StatusBar.tsx      # 状态条
├── index.html
├── package.json
└── vite.config.ts             # dev 代理 /ws → 8000；watch 忽略编辑器临时文件
```

## 命令

```bash
npm install --no-audit --no-fund --ignore-scripts --cache ".npm-cache"   # 装依赖
npm run dev        # dev server :5173（/ws 代理到 127.0.0.1:8000，热更新）
npm run build      # 产出 dist/（tsc 类型检查 + vite build）
```

后端仍在 MiniAgent 目录启动：`.venv\Scripts\python -m uvicorn server.app:app --reload --port 8000`。
dist 存在时 FastAPI 直接托管 React 应用；无 dist 时回退内联 P0 页。

## 本机沙箱注意（仅本开发环境）

- npm 默认缓存目录在工作区外会被沙箱拒绝（EPERM）→ 用工作区内缓存 `--cache ".npm-cache"`。
- npm 生命周期脚本（如 esbuild postinstall）spawn 子进程被沙箱拦截 → `--ignore-scripts`
  （esbuild 二进制由可选依赖 `@esbuild/win32-x64` 提供，无需 postinstall）。
- vite/dev 依赖 esbuild 以管道 spawn 原生二进制 → 运行 vite 命令需放开进程权限
  （DSH 沙箱权限 `danger-full-access`）。
- vite `server.watch.ignored` 已配置忽略 `.tmp/.tmpdir/~xxx.TMP` 临时文件，
  避免编辑器原子写入触发 Windows EBUSY 崩溃。

## 布局持久化

- `localStorage['miniagent_dashboard_v1']`：`{ version: 1, layout, instances }`。
- 组件面板提供导出/导入 JSON 文件按钮，用于备份/分享布局。

## 会话 id

`localStorage['miniagent_sid']`（与 P0 内联页同键名，可接续旧会话）。「新会话」按钮清掉后重载。
