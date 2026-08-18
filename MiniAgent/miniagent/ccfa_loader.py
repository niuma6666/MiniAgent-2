"""CCFA-Skills 集成模块：把 CCFA-Skills 仓库的 SKILL.md 技能家族加载为 MiniAgent Skill。

CCFA-Skills (https://github.com/mikubaka88/CCFA-Skills) 是一个面向 CCF-A 论文的
"研究故事线"技能家族，共 17 个 runtime roles（idea optimizer / paper writer /
paper reviewer / rebuttal writer ...）。每个技能是一个 SKILL.md 文件：

    ---
    name: ccf-paper-writer
    description: "..."
    metadata: {...}
    ---
    # 正文（作为 MiniAgent Skill 的 prompt）

本模块负责：
1. 扫描 CCFA 根目录下所有 `*/SKILL.md`
2. 解析 YAML frontmatter（name / description / metadata）
3. 正文转成 Skill.prompt，注册进 MiniAgent 全局 _SKILLS
4. 关键词取自 description 中的触发短语，供自动路由使用

用法（在 cli.py 或你的入口里）：
    from miniagent.ccfa_loader import load_ccfa_skills
    load_ccfa_skills("path/to/CCFA-Skills")   # 可选 env: CCFA_SKILLS_ROOT

依赖：yaml（pip install pyyaml）。未安装时自动跳过 frontmatter 解析（仅注册正文）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from .logger import get_logger
from .skills import Skill, register_skill

logger = get_logger(__name__)

# 相对引用（../ccf-common/references/xxx.md）在 MiniAgent 环境下的提示
_REF_HINT = (
    "\n\n[参考文件] 本技能正文中提到的 `references/`、`../ccf-common/references/` 等"
    "相对路径文件位于仓库绝对路径 {root}，需要时可用 read 工具读取。"
)


def _parse_frontmatter(text: str) -> tuple[Dict[str, str], str]:
    """解析 SKILL.md 的 YAML frontmatter（--- 包裹的头块）。

    Returns:
        (metadata_dict, body)。metadata 仅含 name/description 等顶层字段。
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text

    header, body = m.group(1), m.group(2)
    meta: Dict[str, str] = {}
    for line in header.splitlines():
        # 只解析顶层 "key: value"（跳过 metadata: 下的嵌套块）
        if line and not line[0].isspace() and ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, body.strip()


_CN_ACTIONS = ["写作", "审稿", "评审", "回复", "答辩", "检索", "搜索", "监控",
               "实验", "设计", "绘图", "可视化", "提交", "检查", "核查", "审计",
               "规划", "拆解", "思路", "想法", "优化", "打分", "排序", "比较",
               "转换", "模板", "脚手架", "初始化", "代码", "论文", "文献", "故事线",
               "改写", "润色", "压缩", "投稿"]

_STOPWORDS = {
    "the", "and", "for", "with", "use", "using", "when", "does", "not",
    "are", "you", "your", "own", "its", "that", "this", "from", "into",
    "main", "maintain", "maintaining", "only", "full", "before", "after",
    "keep", "keeping", "preserve", "create", "creating", "requested",
    "but", "they", "them", "will", "would", "can", "could", "may", "might",
    "must", "should", "shall", "while", "where", "which", "who", "whom",
    "what", "when", "why", "how", "all", "any", "each", "every", "both",
    "some", "such", "than", "then", "there", "here", "also", "even", "still",
    "etc", "e.g", "i.e", "via", "per", "within", "without", "between",
    "under", "over", "about", "against", "during", "among", "toward",
}

# 英文"元词"：指代技能体系本身的词，出现即无区分度（"用ccfa skills里相应的skill"
# 会让 ccf-skill-forger 因 description 里满是这类词而巧合命中）。keywords 抽取时排除，
# 与 skills.py 的 _LOW_DISC_EN 保持一致（两侧都过滤，双保险）。
_META_WORDS = {"ccf", "ccfa", "skill", "skills", "codex"}


def _parse_use_for(description: str) -> List[str]:
    """提取 CCFA description 中的触发列表。

    CCFA 的 description 通常以 'Use for X, Y, Z. Do not use for ...' 或
    'Use before X, Y, Z. Do not ...' 列出触发场景，这是作者精心维护的
    触发词表，比从整段文字里猜词可靠得多。
    """
    triggers: List[str] = []
    for m in re.finditer(r"(?i)\buse (?:for|before|when)\b\s*[:：]?\s*([^.]*)", description):
        seg = m.group(1)
        # 截断到 "Do not"
        seg = re.split(r"(?i)do not\b", seg)[0]
        for part in re.split(r"[;，,。；]", seg):
            p = part.strip().strip(".").strip()
            # 再按 / 拆（如 NeurIPS/CVPR/ICML template）
            for t in re.split(r"[/]", p):
                t = t.strip()
                if t and len(t) >= 2 and t.lower() not in _STOPWORDS:
                    triggers.append(t)
    return triggers


def _keywords_from_description(description: str, high_freq_words: Optional[set] = None) -> List[str]:
    """从 description 中抽取触发词，供自动路由使用。

    优先级：
    1. 'Use for ...' 触发列表（作者维护的权威触发词，中英文都收）
    2. 描述中的中文动作短语
    3. 英文领域词（去停用词；跨 skill 高频无区分度的词如 ccf/ai/paper 除外）

    Args:
        high_freq_words: 在多个 CCFA skill 描述中都出现、失去区分度的英文词集合。
            只作用于第 3 步兜底抽取，不影响 1/2 步（作者维护的触发词）。
    """
    kws: List[str] = []
    seen = set()

    def add(k: str, skip_high_freq: bool = False) -> None:
        k = k.strip()
        if k and len(k) >= 2 and k.lower() not in seen:
            # 元词（ccfa/skill/codex 等）无区分度，任何 query 提到"skill"都会命中，
            # 会让 ccf-skill-forger 这类 description 满是元词的 skill 巧合胜出
            if k.lower() in _META_WORDS:
                return
            if skip_high_freq and high_freq_words and k.lower() in high_freq_words:
                return
            seen.add(k.lower())
            kws.append(k)

    # 0) 先解析 use-for 触发列表；其中的单词（如 "full review" → review）受保护，
    #    高频过滤不删它们——它们是作者维护的核心触发词根
    use_for_triggers = _parse_use_for(description)
    protected = set()
    for t in use_for_triggers:
        for w in re.findall(r"[a-zA-Z][a-zA-Z-]{1,20}", t.lower()):
            if w not in _STOPWORDS:
                protected.add(w)

    # 1) Use-for 触发列表（最可靠，不做高频过滤）
    for t in use_for_triggers:
        add(t)

    # 2) 中文动作短语（description 中任何含动作词的中文分片）
    cn_parts = re.split(r"[，,；;。:：\s]+", description)
    for part in cn_parts:
        part = part.strip()
        if part and re.search(r"[\u4e00-\u9fff]", part) and any(act in part for act in _CN_ACTIONS):
            add(part)

    # 3) 英文领域词（去停用词 + 跨 skill 高频无区分度词，补足触发列表之外的语义词）
    words = re.findall(r"[a-zA-Z][a-zA-Z-]{1,20}", description.lower())
    for w in words:
        if w not in _STOPWORDS:
            if high_freq_words and w in high_freq_words and w not in protected:
                continue
            add(w)

    return kws[:24]


def load_ccfa_skills(ccfa_root: Optional[str] = None) -> List[str]:
    """扫描 CCFA-Skills 根目录，把所有 `*/SKILL.md` 注册为 MiniAgent Skill。

    Args:
        ccfa_root: CCFA-Skills 仓库根目录。为 None 时读取环境变量 CCFA_SKILLS_ROOT。

    Returns:
        成功注册的 skill 名列表。
    """
    root = ccfa_root or os.environ.get("CCFA_SKILLS_ROOT")
    if not root:
        logger.warning("CCFA_SKILLS_ROOT 未设置，跳过 CCFA skills 加载")
        return []

    root_path = Path(root)
    if not root_path.is_dir():
        logger.warning(f"CCFA root 不存在: {root_path}")
        return []

    # 先读一遍所有 description，统计跨 skill 高频英文词（如 ccf/ai/paper）——
    # 这些词在几乎所有 CCFA skill 里都出现，作为关键词没有区分度，反而会
    # 让无关 skill 因一个公共词命中而误胜出。
    skill_files = sorted(root_path.glob("*/SKILL.md"))
    from collections import Counter
    freq: Counter = Counter()
    all_meta: List[tuple] = []
    for skill_md in skill_files:
        try:
            raw = skill_md.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"读取 SKILL.md 失败: {skill_md} ({e})")
            continue
        meta, body = _parse_frontmatter(raw)
        description = meta.get("description", "")
        freq.update(re.findall(r"[a-zA-Z][a-zA-Z-]{1,20}", description.lower()))
        all_meta.append((skill_md, meta, body))
    n = max(1, len(all_meta))
    high_freq = {w for w, c in freq.items() if c >= max(3, n // 3)}

    loaded: List[str] = []
    for skill_md, meta, body in all_meta:
        name = meta.get("name") or skill_md.parent.name
        description = meta.get("description", "") or f"CCFA skill: {name}"
        keywords = _keywords_from_description(description, high_freq)

        # 正文即 prompt；补一个参考文件提示（MiniAgent 读不到 CCFA 的相对引用）
        prompt = body + _REF_HINT.format(root=root_path.resolve())

        # 默认允许搜索 + 文件读写；CCFA 各 skill 实际需要的工具可能更多，
        # 这里放宽为 None（全部工具）以免白名单误伤，需要收紧可自行配置。
        register_skill(Skill(
            name=name,
            prompt=prompt,
            tools=None,          # 使用全部已加载工具
            temperature=0.3,
            max_iterations=30,   # CCFA 流程较长，给足迭代
            description=description,
            keywords=keywords,
        ))
        loaded.append(name)
        logger.info(f"Loaded CCFA skill: {name} ({len(prompt)} chars)")

    if loaded:
        from .logger import get_logger as _g  # noqa: F401
        from rich.console import Console
        Console().print(f"[dim]📦 CCFA skills loaded: {len(loaded)} → {', '.join(loaded)}[/dim]")
    else:
        logger.warning("未在 CCFA root 下找到任何 SKILL.md")
    return loaded
