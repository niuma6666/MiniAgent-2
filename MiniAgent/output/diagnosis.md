# MiniAgent 诊断与改造报告

> 针对你提出的三个问题：① skill 不能自主路由；② 输出质量一般、需集成 CCFA skill；③ agent.py 存在冗余/逻辑错乱/低效。
> 全部修改已完成并通过回归测试（24/24 用例通过）。本文档是根因分析与修改说明，代码改动见 `output/modifications.diff`。

---

## 问题一：Agent 不能根据用户提问自主决定调用什么 skill

### 根因

你的运行日志显示第 1 轮迭代用 DEFAULT SYSTEM PROMPT 且 "no skill loaded"，第 2 轮才加载 skill。核心原因有两点：

1. **没有自动路由机制**：`agent.py` 里 skill 只能通过用户显式说 "use_skill xxx" 或代码里手动 `load_skill()` 加载，`_init_run` 从未根据用户提问自动选 skill。
2. **即使写了路由，中文 `\b` 边界也是错的**（这是我在实现路由时踩到的关键坑）：
   - Python `re` 的 `\b` 把**中文汉字也当作 `\w`**，所以中英边界（如 `的review`、`literature_reviewer的`）**不产生 word boundary**。
   - 旧实现 `re.search(rf"\b{kw}\b", query)` 会导致：
     - `运用literature_reviewer的skill...` → 子串 `reviewer` 先命中 → 错选 reviewer
     - `review this code in src/auth.py` → 子串 `code` 命中 coder → 错选 coder

### 修复（`miniagent/skills.py` + `miniagent/agent.py`）

**① `match_skill(query)` 打分制路由**（`skills.py`），按优先级计分：

| 信号 | 权重 | 说明 |
|---|---|---|
| 显式提及 skill 全名 | 直接胜出 | 按名字长度降序匹配，`literature_reviewer` 先于 `reviewer` 命中 |
| 英文多词短语关键词（如 `code review`） | +3 | 强信号，如 `write me a code review` 必中 reviewer |
| 中文关键词完整命中 / 英文单词命中 | +1 | 英文单词自动匹配单复数变体（`rebuttals` ↔ `rebuttal`） |
| 中文关键词首部动作字命中（`写作`→query 含`写`） | +1 | 解决"写论文初稿"vs"论文跟踪"的动词歧义 |
| description 英文单词与 query 交集 | +1/词 | 弱信号，领域词补充 |
| description 中文短语直接子串 | +2 | 作者维护的触发词表 |
| description 中文短语部分重叠（公共 bigram） | +1/gram，封顶 +3 | 去重后计分，防通用词（论文/检查）重复计分 |

同分决胜：名字更长者优先（更专业的 skill 胜出）。英文关键词匹配统一用手动边界 `(?<![a-zA-Z])kw(?![a-zA-Z])`，彻底绕开 `\b` 的中文陷阱。

**② `_auto_route_skill(query)`**（`agent.py`）：在 `_init_run` 开头调用，自动加载匹配到的 skill；未命中则保持默认流程。新增 `auto_route_skills: bool = True` 开关可关闭。

### 回归测试（`tests/test_skill_routing.py`）

```
OK  运用literature_reviewer的skill，写800字关于deepseek harness的综述 -> literature_reviewer
OK  review this code in src/auth.py                                   -> reviewer
OK  write me a code review of auth.py                                 -> reviewer
OK  写一篇CCF-A级别的论文初稿                                          -> ccf-paper-writer
OK  帮我审稿这篇论文，给出review意见                                   -> ccf-paper-reviewer
... 内置 11/11 + CCFA 13/13 = 24/24 全部通过
```

---

## 问题二：输出质量一般 + 集成 CCFA skill

### 根因

1. **`literature_reviewer` 的 prompt 是"六步闭环方法论"**，对非旗舰模型（你的日志用的是 flash 级模型）太重：既要打分又要交叉验证又要多轮反思，模型执行不动就敷衍输出。
2. **没有 CCFA 学术写作技能家族**：写论文/审稿/rebuttal 等场景没有专业 prompt 可用。

### 修复

**① 精简 `literature_reviewer`**（`skills.py`）：六步闭环 → 四步直给（多轮检索 → 结构规划 → 写作要求 → 反幻觉自检），`temperature=0.4`，`max_iterations=25`。核心改动：禁止编造引文（"检索不到的细节明确标注『未检索到』"）+ 终稿逐条核对引用来源。

**② 新增 `miniagent/ccfa_loader.py`**：把 `mikubaka88/CCFA-Skills` 的 17 个 SKILL.md 自动加载为 MiniAgent Skill：

- 解析 YAML frontmatter（name / description），正文作为 prompt，自动追加"参考文件路径提示"（CCFA 正文里的 `../ccf-common/references/` 相对引用在 MiniAgent 下读不到）
- **关键词抽取**：
  1. 解析 description 中的 `Use for / Use before ...` 触发列表（作者维护的权威触发词，中英文都收，且这些词的词根不受高频过滤影响）
  2. 中文动作短语（含写作/审稿/评审/投稿等动作词的描述分片）
  3. 英文领域词（去停用词 + **跨 skill 高频无区分度词过滤**，如 ccf/ai/paper——它们出现在几乎所有 description 里，作关键词只会让无关 skill 因一个公共词误胜出）
- `tools=None`（用全部工具）、`max_iterations=30`（CCFA 流程长）
- 通过环境变量 `CCFA_SKILLS_ROOT` 启用（`cli.py` 已接入），**不设置则零侵入**

### 启用方式

```bash
# 方式一：环境变量（推荐）
export CCFA_SKILLS_ROOT="/path/to/CCFA-Skills"
python -m miniagent ...

# 方式二：代码里显式加载
from miniagent.ccfa_loader import load_ccfa_skills
load_ccfa_skills("path/to/CCFA-Skills")
```

路由示例（均通过测试）：

| 用户提问 | 命中的 skill |
|---|---|
| 帮我优化一下这个研究idea | ccf-idea-optimizer |
| 写一篇CCF-A级别的论文初稿 | ccf-paper-writer |
| 帮我审稿这篇论文，给出review意见 | ccf-paper-reviewer |
| 写rebuttal回复审稿人意见 | ccf-rebuttal-writer |
| 帮我做一下论文投稿检查 | ccf-submission-checker |
| 帮我把这段论文去去AI味 | ccf-humanization |
| 帮我追踪一下这个方向有没有新论文 | ccf-literature-monitor |

> 已知边界：`ccf-humanization` 的作者定位是 "sidecar preflight, never as the primary task owner"（辅助角色），所以 `帮我用humanize的方式改写这段prose` 会路由到主任务 `ccf-paper-writer`，这符合 CCFA 家族的设计意图。

---

## 问题三：agent.py 冗余 / 逻辑错乱 / 低效

### 发现并修复的问题清单

| # | 问题 | 位置 | 修复 |
|---|---|---|---|
| 1 | **text / native 双模式共用一套 system prompt 模板**，导致原生函数调用模式也被要求输出 `TOOL:`/`ARGS:` 文本——这是逻辑错乱的核心 | `_build_dynamic_system_prompt` | 拆成 `_TEXT_MODE_PROMPT` / `_NATIVE_MODE_PROMPT` 双模板，按 `mode` 分发 |
| 2 | **`_use_skill_handler` 加载失败时误调 `_reset_skill_state()`**，把已加载的 skill 状态清空 | `_use_skill_handler` | 失败时只记录错误，不再重置状态 |
| 3 | **`run_with_native_tools` 无工具调用时直接返回**，与 text 模式行为不一致（text 模式会启发式判断是否结束） | `run_with_native_tools` | 复用与 text 模式一致的结束判断；continue 前先把消息 append 进 messages（否则原地打转） |
| 4 | **`run_with_tools` 结尾与 `_force_final_answer` 重复**（同一段"强制总结"代码写了两遍） | `run_with_tools` | 结尾统一调用 `_force_final_answer` |
| 5 | **27 个工具每轮迭代重复拼接描述**，token 浪费大 | `_build_tools_prompt` | 按工具名元组做缓存键，工具/技能变化时失效（`add_tool`/`_reset_skill_state` 中清缓存） |
| 6 | **`Skill` 缺 keywords/description 路由元数据** | `skills.py` | dataclass 新增 `keywords` 字段，5 个内置 skill 补齐中英双语的 description 与 keywords |
| 7 | **docstring 中 `\b`/`\w` 未转义**（Python 3.12+ 报 SyntaxWarning） | `skills.py` | 转义为 `\\b`/`\\w` |

### 改动统计

```
miniagent/agent.py  | 132 +++...--------
miniagent/cli.py    |   9 ++
miniagent/skills.py | 188 +++...-----------
miniagent/ccfa_loader.py  | 新增（~200 行）
tests/test_skill_routing.py | 新增（回归测试）
```

---

## 文件清单

| 文件 | 说明 |
|---|---|
| `output/modifications.diff` | 修改前后完整 diff（git 基线 `original snapshot`） |
| `tests/test_skill_routing.py` | 路由回归测试（24 用例） |
| `miniagent/ccfa_loader.py` | CCFA-Skills 集成加载器（新增） |
| `miniagent/skills.py` | 打分制路由 + 内置 skill 增强 |
| `miniagent/agent.py` | 自动路由、双模式模板、缓存、状态修复 |
| `miniagent/cli.py` | CCFA_SKILLS_ROOT 环境变量接入 |

## 下一步建议

1. 真机跑一轮（配好 API key + `CCFA_SKILLS_ROOT`），重点观察：第 1 轮迭代是否直接带出正确 skill、native 模式下是否不再输出 `TOOL:` 文本。
2. 若 CCFA 某些 skill 的触发词命中率不够，直接编辑对应 `SKILL.md` 的 description 的 `Use for` 列表即可——路由会自动生效，无需改代码。
3. `ccf-common` 是公共治理 skill（routing/trigger registry），建议保持 `tools=None` 但注意它也可能被自动路由命中；如果不需要可忽略。
