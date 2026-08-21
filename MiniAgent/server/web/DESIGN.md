# MiniAgent Web 设计规范（DESIGN.md）

> 本项目的前端**设计 skill**。所有前端改动（含 P3 桌宠）必须遵循本文件，禁止绕过 token 硬编码。
>
> **锚点**：温馨橙红暖白风（主色 `#E86F42`，暖白底，圆角 12px，柔和阴影）。
> **骨架**：Anthropic frontend-design 方法论——token 优先、单锚点、克制、全站一致。
> **范围**：仅浅色主题（决策：P2.5 只做浅色）。

---

## 0. 总原则

1. **单锚点**：全站只使用本文件定义的 token；新颜色/圆角/阴影必须先加进 token 表再使用。
2. **克制**：阴影柔和、圆角统一、动效 150–250ms、无渐变（纯色为主）、无超粗边框。
3. **一致**：同一种元素（按钮/卡片/标签/输入框）全站一个样子。
4. **温馨**：暖白底 + 橙红点缀 + 圆润角 + 轻阴影；避免冷灰、纯黑、高饱和刺眼色。

## 1. 色彩 token

### 1.1 品牌橙（主色 `#E86F42`，9 档色阶）

| token | 值 | 用途 |
|---|---|---|
| `--c-orange-50` | `#FEF3EE` | 极浅底、选中底 |
| `--c-orange-100` | `#FDE4D9` | 浅底（气泡/标签） |
| `--c-orange-200` | `#FAC6B3` | 浅边框 |
| `--c-orange-300` | `#F5A386` | 悬停边框 |
| `--c-orange-400` | `#EF835F` | 主色 hover |
| `--c-orange-500` | `#E86F42` | **主色**（按钮/链接/强调） |
| `--c-orange-600` | `#D85A2E` | 主色 active |
| `--c-orange-700` | `#B74A26` | 深色点缀 |
| `--c-orange-800` | `#933D22` | 仅深底文字 |

### 1.2 暖白中性（背景/边框/文字）

| token | 值 | 用途 |
|---|---|---|
| `--bg-page` | `#FBF7F4` | 页面底（暖白） |
| `--bg-panel` | `#FFFFFF` | 面板/卡片底 |
| `--bg-subtle` | `#F7F1EC` | 次级底（输入框/代码块/条目） |
| `--border` | `#F0E7E0` | 边框/分割线 |
| `--border-strong` | `#E4D8CF` | 强调边框（hover/焦点） |
| `--text-1` | `#3D322E` | 主文字（暖黑） |
| `--text-2` | `#8C7E76` | 次级文字 |
| `--text-3` | `#B5A9A1` | 弱化/占位 |

### 1.3 语义色（暖调）

| token | 值 | 用途 |
|---|---|---|
| `--c-ok` | `#5C9E63` | 成功/完成 |
| `--c-warn` | `#E8A23D` | 运行中/警告 |
| `--c-danger` | `#D9544F` | 错误/危险 |
| `--c-ok-bg` | `#EFF7EF` | 成功浅底 |
| `--c-warn-bg` | `#FDF5E7` | 警告浅底 |
| `--c-danger-bg` | `#FDF0EE` | 错误浅底 |

### 1.4 交互叠加层

| token | 值 | 用途 |
|---|---|---|
| `--hover-overlay` | `rgba(232,111,66,.06)` | 可点元素 hover |
| `--hover-overlay-strong` | `rgba(232,111,66,.12)` | hover 加深/active |

## 2. 字体

- **正文**：`-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif`
- **代码**：`"SF Mono", "JetBrains Mono", "Fira Code", Consolas, "PingFang SC", "Microsoft YaHei"`
- **字号阶梯**：12（辅助）/ 13（面板内）/ 14（正文）/ 16（强调）/ 20（标题）
- **行高**：正文 1.6，紧凑 1.4；工具/JSON 用代码字体 + 12–13px

## 3. 圆角 / 间距 / 阴影 / 动效

| token | 值 | 用途 |
|---|---|---|
| `--r-sm` | `8px` | 小元素、标签、工具卡片 |
| `--r-md` | `12px` | **基础**：面板/按钮/输入框/气泡 |
| `--r-lg` | `16px` | 大面板、弹窗 |
| `--r-full` | `999px` | 胶囊、头像、状态点 |
| `--space-1..4` | `4/8/12/16px` | 间距（4 的倍数） |
| `--shadow-sm` | `0 1px 2px rgba(122,52,31,.06), 0 1px 3px rgba(122,52,31,.04)` | 卡片常规 |
| `--shadow-md` | `0 2px 8px rgba(122,52,31,.08)` | 浮起/弹窗 |
| `--shadow-lg` | `0 8px 24px rgba(122,52,31,.12)` | 遮罩层内容 |
| `--ease` | `cubic-bezier(.4,0,.2,1)` | 全站缓动 |
| `--dur-fast` | `150ms` | hover/按压 |
| `--dur` | `250ms` | 展开/过渡 |

## 4. 组件规范

### 4.1 顶栏
- 白底（`--bg-panel`），下边框 `--border`，高度 52px，`--shadow-sm`。
- 品牌区：16px 橙红圆点（`--c-orange-500`）+ "MiniAgent Web" 标题（`--text-1`，加粗）。
- 会话/连接信息用胶囊（`--bg-subtle` 底 + `--r-full`），状态点绿=`--c-ok` 红=`--c-danger`。

### 4.2 按钮
- 主按钮：`--c-orange-500` 底、白字、`--r-md`；hover→`--c-orange-400`，active→`--c-orange-600`；过渡 `--dur-fast`。
- 次要按钮：白底、`--border` 边框、`--text-1`；hover→`--bg-subtle`。
- 危险按钮：白底、`--c-danger` 边框/文字；hover→`--c-danger-bg`。
- 禁用：opacity .55 + `not-allowed`。

### 4.3 输入框
- 白底、`--border` 边框、`--r-md`；focus → `--border-strong` + 2px 橙红外环（`box-shadow: 0 0 0 3px rgba(232,111,66,.15)`）。

### 4.4 面板 / 画布组件
- 白底 + `--r-md` + `--shadow-sm` + `--border`。
- 面板头：`--text-1` 600 字重 13px，下边框 `--border`；作为 RGL 拖拽手柄时 `cursor: move`。
- 选中态（画布组件）：外环 2px `--c-orange-500`。

### 4.5 聊天区
- 用户消息：**右对齐气泡**，`--c-orange-100` 底、`--text-1`、`--r-md`（右下角 4px 微调营造对话感）。
- assistant 回答：**全宽无气泡**流式正文（`--text-1`），markdown 代码块用 `--bg-subtle` 底。
- status 行：12px、`--text-2`，前缀"… "，可选橙点。
- 错误行：`--c-danger-bg` 底 + `--c-danger` 文字，`--r-sm`，内边距 8px。
- 工具行（聊天内联）：代码字体 12px，名称 `--c-orange-600`，结果 `--text-2`。

### 4.6 工具卡片（工具日志）
- 白底 + `--r-sm` + `--border`；左侧 3px 状态色条（运行中 `--c-warn` / 完成 `--c-ok` / 失败 `--c-danger`）。
- 头部：名称（代码字体 600）+ elapsed 徽标（`--bg-subtle` 胶囊）。
- 折叠：默认只显头部，点击展开 args/result（`pre`，`--bg-subtle` 底，代码字体，过渡 `--dur`）。
- 运行中卡片：`--c-warn-bg` 底 + 琥珀边框，⏳ 前缀。

### 4.7 组件面板 / 属性面板
- 侧栏白底、右侧/左侧 `--border` 分隔。
- 条目：hover → `--bg-subtle` + `--border-strong`；标签 600，描述 11px `--text-2`。
- 空状态：居中 `--text-3` + 橙红小图标（内联 SVG），留白充足。

### 4.8 确认弹窗
- 遮罩 `rgba(61,50,46,.4)`；弹窗白底 `--r-lg` + `--shadow-lg`。
- 标题 600；描述 `--bg-subtle` 底代码字体；允许=主色按钮、拒绝=危险按钮。

### 4.9 滚动条（Webkit）
- 轨道透明，滑块 `--border-strong` 圆角，hover 加深。

## 5. 禁止清单（AI 味规避）

- ❌ 紫色/蓝色渐变、五彩渐变、金属质感
- ❌ 超重阴影（黑 0.3+）、粗黑边框
- ❌ 未定义 token 的裸色值/圆角/阴影
- ❌ 每屏换一种风格、随机强调色
- ❌ 大圆角滥用（卡片 24px+）、图标五彩斑斓
- ❌ 冷灰纯灰背景（`#eee`/`#f5f5f5`）——一律用暖白系

## 6. 使用方式

- 改样式：先查本文件 token，能复用不复造；需要新值 → 先在此登记再使用。
- 新组件（如 P3 桌宠）：按 4.x 规范对齐配色/圆角/动效，不引入新依赖。
- 布局持久化 / 事件协议与本规范无关（见 PROTOCOL.md）。
