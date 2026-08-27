# MiniAgent Web 事件协议（v2.1）

> 状态：P0 冻结版 v1 之上扩展（P1 第一步会话化）。P2 的所有组件（聊天、工具日志、状态条、桌宠）都依赖本协议开发。
> 变更协议必须同步更新本文件，并在冻结期外通过评审。
>
> v2 变更：新增 `hello` 握手（会话认领/创建/历史恢复）、并发拒绝语义；`chat` 语义从"每问全新上下文"改为"会话内多轮记忆"。
> v2.1 变更：**事件广播**——同一会话可同时挂多个连接（如仪表盘 + 桌宠），每个连接各自收到完整事件流，互不竞争；无连接期间的事件进 backlog，重连后一次性补发。线格式（事件类型/字段）不变。

## 传输

- 端点：`ws://<host>:8000/ws`（FastAPI WebSocket）
- 格式：JSON 文本帧（`ws.send_json` / `receive_json`）
- 连接生命周期：**会话跨连接存活**（内存版）。连接建立后首帧必须是 `hello`；断开只销毁该连接的 pump，Session 保留，重连可恢复。
- **广播（v2.1）**：同一会话的多个连接各自收到完整事件流（每连接一个独立事件队列，`push` 扇出到所有活动连接，互不竞争）。**断线补发**：没有任何活动连接期间产生的事件累积进会话 backlog，下一个注册的连接按序一次性补发；其他连接仍在线时新加入的连接只从加入时刻起接收实时事件（错过的运行状态由 `hello.running` + `history` 兜底）。确认桥 `confirm_response` 任意连接回应均生效（服务端按 id 幂等，先到先得）。
- 页面托管（P2）：`server/web/` 是 React 前端（Vite + React 18 + TS + react-grid-layout）。构建产物 `server/web/dist` 存在时，`GET /` 返回 React 应用、`/assets/{path}` 托管静态资源（带目录穿越防护）；dist 不存在时回退到内联 P0 页面。开发模式用 vite dev（5173 端口，`/ws` 代理到本服务）。

---

## 客户端 → 服务器

### `hello`（连接后首帧，必发）
认领或创建会话。

```json
{"type": "hello", "session_id": null}
```

- `session_id`: 来自 localStorage 的既有会话 id；`null` / 缺失 / 服务器找不到 → 服务端新建会话。
- 服务器回 `hello`（见下），客户端用返回的 id 覆盖 localStorage。

### `chat`
发送用户消息，触发一次 agent 运行。

```json
{"type": "chat", "text": "列一下当前目录的文件"}
```

- `text`: 必填，用户输入原文。
- **多轮记忆**：服务端自动把当前消息与历史拼接（CLI 同款格式）后喂给 agent；完成后把本轮 user+assistant 追加进会话历史（最多保留最近 10 轮）。
- **并发拒绝**：上一条 `chat` 仍在运行时，新的 `chat` 直接收到 `error`（`"上一条请求仍在运行，请稍候"`），不排队。

### `confirm_response`
回应服务端的 `confirm_request`（确认桥）。

```json
{"type": "confirm_response", "id": "c-1", "allow": true}
```

- `id`: 原样带回 `confirm_request` 的 id。
- `allow`: `true` 允许 / `false` 拒绝。
- 客户端应尽快回应；**超时（`CONFIRM_TIMEOUT` 秒，默认 60）或连接断开未回应 → 服务端按"拒绝"处理**（不卡死 agent）。

---

## 服务器 → 客户端

### `hello`（回应握手）
```json
{"type": "hello", "session_id": "abc123", "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}], "running": false}
```

- `session_id`: 实际生效的会话 id（客户端应覆盖本地存储）。
- `history`: 最近对话（最多 10 轮），`role` ∈ `user | assistant`；新会话为空数组。
- `running`: 该会话是否正在运行（B2）。运行中刷新重连时前端据此禁用输入；`done`/`error` 到达后恢复。
- 前端约定：按顺序渲染 history；随后正常处理后续事件。

### `confirm_request`
agent 请求用户确认（写/改文件、危险 bash 命令）。

```json
{"type": "confirm_request", "id": "c-1", "desc": "写入文件 D:/x/foo.py"}
```

- `id`: 唯一标识，客户端须原样带回 `confirm_response`。
- `desc`: 需确认的操作描述（如 "写入文件 <路径>" / 危险命令原文）。
- 前端约定：弹窗展示 `desc`，用户点允许/拒绝后回 `confirm_response`。
- agent 在收到回应前**同步阻塞**（工作线程），期间 `chat` 并发闸仍生效。

### `stream`
agent 流式输出的**单个 token 分片**。

```json
{"type": "stream", "token": "当前"}
```

注意：text 模式下，模型回复中夹杂的 `TOOL:/ARGS:` 文本块会被服务端抑制，**不会**推送到这里（见"抑制规则"）。

### `status`
每轮（iteration）开始时的状态提示。

```json
{"type": "status", "text": "Thinking (Iteration 1)..."}
```

前端约定：收到 `status` 时清空当前答案容器（新一轮开新段）。

### `tool_start` / `tool_end`
工具调用开始 / 结束。

```json
{"type": "tool_start", "name": "bash", "args": {"cmd": "ls -la"}}
{"type": "tool_end", "name": "bash", "result": {"exit_code": 0, "stdout": "..."}, "elapsed": 1.2}
```

- `args`: 工具参数字典（P0 前端直接 `JSON.stringify` 展示）。
- `result`: 工具返回值，可能是**对象 / 字符串 / null**，前端用 `JSON.stringify` 转可读文本（对象直转字符串会得到 `[object Object]`，已修复）。
- `elapsed`: 单次工具耗时（秒）。
- **已知行为**：工具执行**异常**时服务端不发 `tool_end`（错误文本直接回传给模型，仅影响 LLM 下一步判断）。

### `done`
一次运行结束，携带最终答案。

```json
{"type": "done", "answer": "…", "elapsed": 42.0}
```

- `answer`: 最终回答。服务端已剥掉 `FINAL_ANSWER:` 前缀（模型同回复写两版时，第二个前缀不保证剥离，见"已知限制"）。
- 前端约定：用 `answer` **替换**当前答案容器内容，**不新增**块（消除重复显示）。

### `error`
运行失败（LLM 调用异常、流式中止等）。

```json
{"type": "error", "message": "TimeoutError: LLM 流式输出停滞（超过 120s 无数据），已中止。"}
```

---

## 抑制规则（服务端，text 模式）

`Session.__call__`（即 `stream_callback`）逐 token 累积，累积文本中出现 `TOOL:` / `Tool:` / `工具:` 之一后，**本轮剩余 token 全部抑制**，不再推送。`run_with_tools` 每轮 LLM 调用前自动调用 `reset()` 清除累积状态。

效果：工具调用块不会以 `stream` 形式泄漏到前端；工具信息只通过 `tool_start/tool_end` 呈现。

---

## 前端显示约定（P0 实现）

1. `chat` 发送时：先追加用户消息，再新建一个空答案容器（追加在对话末尾）。
2. `stream`：token 累积进当前答案容器并渲染（`appendChild` 移动语义保证容器始终在列表末尾）。
3. `status`：清空当前答案容器 + 追加一行状态。
4. `done`：用 `answer` 替换容器内容。
5. 渲染前剥离开头 `FINAL_ANSWER:` 前缀。
6. markdown 渲染：marked（bootcdn 主源 + jsdelivr 兜底；不可用时退回转义纯文本）。

---

## P2 前端约定（React 仪表盘，v2 之上）

代码位置：`server/web/`（Vite + React 18 + TypeScript + zustand + react-grid-layout）。
双模式：dev = `npm run dev`（5173，`/ws` 代理到 8000，热更新）；prod = `npm run build` 后由 FastAPI 托管（见"传输"）。

### 状态模型（单一事件源）

- zustand store（`src/store.ts`）持有 `items: ChatItem[]`（聊天流，含 user / status / tool / error / answer 五类），工具日志面板与状态条都从 `items` 派生，避免多份状态不同步。
- WS 事件统一投递到 `store.applyEvent`；`ws.ts` 只负责连接/重连/发送（模块级单例，`hello` 时读写 `localStorage.miniagent_sid`，与 P0 同键名）。
- 渲染语义继承 P0：`status` 清空当前答案容器并记一行、`done` 用 `answer` 替换、渲染前剥离 `FINAL_ANSWER:` 前缀、marked 渲染（异常退回转义纯文本）。
- 确认桥：`confirm_request` → 弹窗 → `confirm_response` 原样回带 id。

### 拖拽画布与布局持久化

- 画布 = react-grid-layout（12 列），组件注册表在 `src/widgets.tsx`（新增组件只需登记 render + 尺寸）。
- 布局 JSON 存 `localStorage['miniagent_dashboard_v1']`：`{ version: 1, layout: Layout[], instances: { id: { type, props } } }`；支持导出/导入 JSON 文件（组件面板按钮）。
- 拖拽手柄 = 各组件标题栏（`.panel-head`）；选中组件后在右侧属性面板改标题、移除组件。

### 已知限制（P2 状态追加）

- **同会话多连接已支持（v2.1 广播）**：同一会话多个连接各自收全量事件流，仪表盘 + 桌宠可共存；多标签页同开也各自完整。布局持久化为浏览器本地（localStorage）：换浏览器/清缓存即重置（可用导出 JSON 备份）。
- 布局持久化为浏览器本地（localStorage）：换浏览器/清缓存即重置（可用导出 JSON 备份）。
- dev 模式依赖 vite（Node ≥ 20）；本机沙箱环境下 npm 需 `--ignore-scripts` + 工作区内缓存，vite 命令需放开进程权限（见 `server/web/README.md`）。

---

## 已知限制（P1 完成状态）

- **会话为内存版**：服务器重启即清空（决策：内存版；落盘为后续可选步骤）。
- **闲置回收**：超过 `SESSION_IDLE_TIMEOUT`（默认 1800s）无活动的会话被后台任务回收（`cleanup()` 停 MCP）；正在运行的会话不回收。连接活跃（收到任何消息）即视为会话活跃。
- **断线补发**：断线期间 agent 产生的事件累积在会话队列里，重连后由新连接的 pump 补发（可能一次性刷出多条）。
- **同会话多连接（v2.1 已解决）**：事件广播到该会话所有活动连接，不再随机分发（原"随机分发给其中一个连接"限制已移除）。
- **模型一稿两写**：模型可能在同一条回复里先写草稿再写 `FINAL_ANSWER:` 正式版，前端只消除"显示重复"，去不掉多写内容（后端启发式处理暂缓）。
- **MCP 已接入**：会话首次 `chat` 时按 `mcp.json` 加载 MCP 工具（tavily_search/tavily_extract 等），客户端在会话清理/服务器关闭时 stop（复刻 cli.py 的 finally 清理，防残留 npx 子进程）。每个会话独立 spawn 一个 MCP 子进程（npx mcp-remote），首次启动有秒级延迟；单个服务器加载失败只记日志不影响服务。
- **CCFA-Skills 不加载**（决策）：Web 界面不加载 CCFA skill，保持轻量对话；CLI 终端行为不受影响。内置 skill（coder/researcher 等）仍随框架自动注册。
- **确认已开启**：`confirm_file_writes`（写/改文件）与 `confirm_dangerous`（危险 bash）默认开启，走 `confirm_request/confirm_response` 桥；超时 `CONFIRM_TIMEOUT`（默认 60s）或连接断开按拒绝处理，agent 不卡死。
- **初始化失败可见**：agent 构建失败（缺 API key、MCP 加载崩等）推 `error` 事件（`初始化失败：…`），不会静默挂起。

---

## 环境变量（server 层）

| 变量 | 默认 | 说明 |
|---|---|---|
| `CONFIRM_TIMEOUT` | 60 | 确认请求等待秒数，超时按拒绝 |
| `SESSION_IDLE_TIMEOUT` | 1800 | 会话闲置回收阈值（秒） |
| （沿用框架）`LLM_API_KEY` / `LLM_MODEL` / `LLM_API_BASE` / `CONFIRM_FILE_WRITES` / `CONFIRM_DANGEROUS` / `CCFA_SKILLS_ROOT` 等 | — | 见 `miniagent` 侧 AGENTS.md |

---

## 自检（回归固化）

```powershell
# 只跑不依赖服务器的单测（不耗 API）
.venv\Scripts\python server/selftest.py --standalone

# 全量：单测 + E2E（需服务器在跑；E2E 会真实调用 LLM）
.venv\Scripts\python server/selftest.py
```

覆盖：事件流完整、会话恢复+多轮引用、并发拒绝、确认允许/拒绝、确认超时、构建失败兜底、pump 静默退出、闲置回收。

---

## 变更流程

1. 修改 `server/app.py` 的事件收发逻辑时，同步更新本文档。
2. 事件类型、字段名是前后端契约，**冻结期内不改名**；确需变更 → 升版本号并双端同步。
