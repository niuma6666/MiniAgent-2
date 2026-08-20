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

def _build_ref_hint(root: Path, skill_dir: Optional[Path] = None) -> str:
    """构建参考文件提示：列出仓库里**实际存在**的 references 文件（绝对路径）。

    技能正文常引用 `references/`、`../ccf-common/references/xxx.md` 等相对路径，
    但当前仓库往往缺失大部分 references 文件。若只给仓库根路径，agent 会按正文
    瞎猜路径（read 到不存在的文件），再退而 glob 整个仓库找文件——既浪费 token
    又偏离主线。这里直接给出实际存在的文件清单，并明示缺失文件应跳过、禁止
    glob 全仓库。
    """
    ref_dirs: List[Path] = []
    if skill_dir is not None:
        ref_dirs.append(skill_dir / "references")
    ref_dirs.append(root / "ccf-common" / "references")

    found: List[Path] = []
    for d in ref_dirs:
        if d.is_dir():
            found.extend(sorted(d.iterdir()))
    if not found:
        return (
            "\n\n[参考文件] 本技能正文中提到的 `references/`、`../ccf-common/references/` 等"
            "相对路径文件在当前仓库中不存在（仓库不完整）。引用到这些文件时直接跳过，"
            "不要用 glob 扫描整个仓库找文件。"
        )
    paths = "\n".join(f"  - {p.resolve()}" for p in found)
    return (
        "\n\n[参考文件] 本技能正文提到的 references 相对路径，当前仓库实际存在的文件如下"
        "（用 read 工具按绝对路径读取；不在列表中的文件不存在，直接跳过，不要 glob 整个仓库）：\n"
        + paths
    )

# 正文中 references 相对引用路径（如 references/x.md、../ccf-common/references/y.md、
# ../ccf-humanization/references/z.md、references/venue-guides/index.md）
_REF_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_\-])((?:\.\./)*(?:[A-Za-z0-9_\-]+/)*references/"
    r"[A-Za-z0-9_\-./]+\.(?:md|yaml))"
)


def _annotate_references(body: str, root: Path, skill_dir: Path) -> str:
    """逐条标注正文中的 references 相对引用：存在 → 附绝对路径；缺失 → 明示跳过。

    CCFA skill 正文常以强指令要求"必须应用 references/xxx.md"，而本地仓库缺失
    大部分文件——仅靠正文末尾的清单提示（_build_ref_hint）压不过这些指令，
    agent 仍会 glob/read 不存在的文件（空转工具调用）。这里把"存在/缺失"信息
    直接贴到每个引用处，让指令与事实的冲突当场消解。
    """
    def _repl(m: re.Match) -> str:
        ref = m.group(1)
        parts = [p for p in ref.split("/") if p not in ("", ".")]
        while parts and parts[0] == "..":
            parts.pop(0)
        # 相对基准：第一段为技能目录名（ccf-*）→ 仓库根下；否则 skill 自身目录
        base = root if (parts and parts[0].startswith("ccf-")) else skill_dir
        candidate = base.joinpath(*parts)
        if candidate.is_file():
            return f"{m.group(0)} [exists: {candidate.resolve()}]"
        return f"{m.group(0)} [MISSING in local repo — skip any step requiring this file]"

    return _REF_PATH_RE.sub(_repl, body)

# 惰性模式下只读文件头解析 frontmatter 的字节上限。
# CCFA 各 SKILL.md 的 frontmatter（name/description/metadata）都在文件最前面，
# 实际远小于 16KB；若头部未闭合则回退读全文（见 _read_frontmatter）。
_FRONTMATTER_HEAD = 16 * 1024


def _parse_header(header: str) -> Dict[str, str]:
    """解析 frontmatter 头块中顶层 "key: value"（跳过 metadata: 下的嵌套块）。"""
    meta: Dict[str, str] = {}
    for line in header.splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


def _parse_frontmatter(text: str) -> tuple[Dict[str, str], str]:
    """解析 SKILL.md 的 YAML frontmatter（--- 包裹的头块）。

    Returns:
        (metadata_dict, body)。metadata 仅含 name/description 等顶层字段。
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    return _parse_header(m.group(1)), m.group(2).strip()


def _read_frontmatter(path: Path, with_body: bool) -> tuple[Dict[str, str], str]:
    """读取一个 SKILL.md 的 frontmatter。

    with_body=True:  读全文，返回 (meta, body)。
    with_body=False: 只读文件头解析 frontmatter，返回 (meta, "")——正文不读入内存，
                     技能被路由选中后再由 ensure_skill_prompt() 读取（按需加载）。

    极端情况（frontmatter 超出头部上限未闭合）会回退读全文，但仍只保留 meta。
    """
    if with_body:
        text = path.read_text(encoding="utf-8", errors="replace")
        return _parse_frontmatter(text)
    head = path.read_bytes()[:_FRONTMATTER_HEAD].decode("utf-8", errors="replace")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", head, re.DOTALL)
    if m:
        return _parse_header(m.group(1)), ""
    # 头部未闭合：回退读全文，但只取 frontmatter（正文仍不保留）
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, _body = _parse_frontmatter(text)
    return meta, ""


_CN_ACTIONS = ["写作", "审稿", "评审", "回复", "答辩", "检索", "搜索", "监控",
               "实验", "设计", "绘图", "可视化", "提交", "检查", "核查", "审计",
               "规划", "拆解", "思路", "想法", "优化", "打分", "排序", "比较",
               "转换", "模板", "脚手架", "初始化", "代码", "论文", "文献", "故事线",
               "改写", "润色", "压缩", "投稿"]

# 英文停用词/元词表以 skills.py 为唯一数据源（match_skill 与 keywords 抽取
# 共用同一份，避免两份表不同步导致路由打分与关键词抽取行为漂移）。
# 保留别名，内部引用无需改动。
from .skills import _EN_STOPWORDS as _STOPWORDS  # noqa: E402
from .skills import _LOW_DISC_EN as _META_WORDS  # noqa: E402


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


def ensure_skill_prompt(skill: Skill) -> bool:
    """按需加载：把 skill 的 SKILL.md 正文读入 skill.prompt（幂等）。

    路由只依赖注册时解析好的 name/description/keywords；正文（可能数万字）在
    技能真正被选中后才调用本函数从磁盘读取，并缓存进 skill.prompt——
    这样启动时无需把整个 CCFA 家族正文驻留内存。

    Returns:
        True 表示 prompt 可用（已内联，或本次读取成功）；False 表示读取失败。
    """
    if skill.prompt:
        return True
    if not skill.prompt_file:
        return False  # 既无内联 prompt 也无来源文件：不可用
    try:
        path = Path(skill.prompt_file)
        _meta, body = _parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        root = path.parent.parent.resolve()
        # 正文即 prompt：逐条标注 references 引用（存在→绝对路径，缺失→明示跳过），
        # 再补末尾清单提示（列出实际存在的文件）
        skill.prompt = _annotate_references(body, root, path.parent) + _build_ref_hint(root, skill_dir=path.parent)
        logger.info(f"Lazily loaded CCFA skill body: {skill.name} ({len(skill.prompt)} chars)")
        # 与其他运行时日志同风格（dim 灰字），让用户看到 CCFA 正文按需读取的时机
        from rich.console import Console
        Console().print(f"[dim]📖 CCFA skill body loaded: {skill.name} ({len(skill.prompt)} chars)[/dim]")
        return True
    except Exception as e:
        logger.warning(f"按需读取 SKILL.md 失败: {skill.prompt_file} ({e})")
        return False


def load_ccfa_skills(ccfa_root: Optional[str] = None, lazy: bool = True) -> List[str]:
    """扫描 CCFA-Skills 根目录，把所有 `*/SKILL.md` 注册为 MiniAgent Skill。

    Args:
        ccfa_root: CCFA-Skills 仓库根目录。为 None 时读取环境变量 CCFA_SKILLS_ROOT。
        lazy: True（默认）按需加载——注册时只解析 frontmatter（name/description/
            keywords，路由必需），SKILL.md 正文待技能被路由选中后由
            ensure_skill_prompt() 从磁盘读取。False 则在注册时读全文。

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
            meta, _body = _read_frontmatter(skill_md, with_body=False)
        except Exception as e:
            logger.warning(f"读取 SKILL.md 失败: {skill_md} ({e})")
            continue
        description = meta.get("description", "")
        freq.update(re.findall(r"[a-zA-Z][a-zA-Z-]{1,20}", description.lower()))
        all_meta.append((skill_md, meta))
    n = max(1, len(all_meta))
    high_freq = {w for w, c in freq.items() if c >= max(3, n // 3)}

    loaded: List[str] = []
    for skill_md, meta in all_meta:
        name = meta.get("name") or skill_md.parent.name
        description = meta.get("description", "") or f"CCFA skill: {name}"
        keywords = _keywords_from_description(description, high_freq)

        if lazy:
            # 按需加载：正文（可能数万字）先不读，路由选中后由 ensure_skill_prompt 读取
            prompt = ""
            prompt_file = str(skill_md)
        else:
            _meta, body = _read_frontmatter(skill_md, with_body=True)
            # 正文即 prompt：逐条标注 references 引用 + 末尾清单提示
            prompt = _annotate_references(body, root_path, skill_md.parent) + _build_ref_hint(root_path, skill_dir=skill_md.parent)
            prompt_file = None

        # 默认允许搜索 + 文件读写；CCFA 各 skill 实际需要的工具可能更多，
        # 这里放宽为 None（全部工具）以免白名单误伤，需要收紧可自行配置。
        register_skill(Skill(
            name=name,
            prompt=prompt,
            prompt_file=prompt_file,
            tools=None,          # 使用全部已加载工具
            temperature=0.3,
            max_iterations=30,   # CCFA 流程较长，给足迭代
            description=description,
            keywords=keywords,
        ))
        loaded.append(name)
        logger.info(f"Loaded CCFA skill: {name} ({'lazy' if lazy else str(len(prompt)) + ' chars'})")

    if loaded:
        from .logger import get_logger as _g  # noqa: F401
        from rich.console import Console
        mode = "lazy" if lazy else "eager"
        Console().print(f"[dim]📦 CCFA skills loaded: {len(loaded)} ({mode}) → {', '.join(loaded)}[/dim]")
    else:
        logger.warning("未在 CCFA root 下找到任何 SKILL.md")
    return loaded
