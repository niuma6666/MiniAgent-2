"""Skill system for MiniAgent.

A Skill is a reusable configuration that bundles:
- A specialized system prompt
- An optional tool whitelist (subset of loaded tools)
- Optional LLM parameters (temperature, max_iterations)

Skills let you create purpose-built agent personas without writing new code.

Example usage:
    from miniagent.skills import register_skill, get_skill

    @register_skill
    def code_reviewer():
        return Skill(
            name="code_reviewer",
            prompt="You are a senior code reviewer. Focus on bugs, security, and readability.",
            tools=["read", "grep", "glob"],
            temperature=0.3,
        )

    # Use in agent
    agent.load_skill("code_reviewer")
    agent.run("Review the changes in src/auth.py")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Global skill registry
_SKILLS: Dict[str, "Skill"] = {}


@dataclass
class Skill:
    """A reusable agent configuration."""
    name: str
    prompt: str
    tools: Optional[List[str]] = None  # None = use all loaded tools
    temperature: Optional[float] = None
    max_iterations: Optional[int] = None
    description: str = ""
    # 路由关键词：命中用户提问即自动加载该 skill（解决"不能自主选择 skill"问题）
    keywords: List[str] = field(default_factory=list)


def register_skill(skill: Skill) -> Skill:
    """Register a skill in the global registry.
    
    Can be used as a plain call:
        register_skill(Skill(name="writer", prompt="..."))
    
    Args:
        skill: Skill instance to register.
        
    Returns:
        The registered Skill (for chaining).
    """
    _SKILLS[skill.name] = skill
    return skill


def _split_terms(text: str) -> tuple[set, set]:
    """把文本拆成英文单词集合 + 中文短语集合（用于匹配打分）。

    注意：不能依赖 re 的 \\b——中文也属于 \\w，\\b 在中英边界不生效。
    """
    en = set(re.findall(r"[a-zA-Z][a-zA-Z-]{1,30}", text.lower()))
    cn = set()
    for part in re.split(r"[，,；;。：:\s]+", text):
        part = part.strip()
        if part and re.search(r"[\u4e00-\u9fff]", part):
            cn.add(part)
    return en, cn


def _cn_2grams(text: str) -> set:
    """提取文本中所有连续的两个汉字（中文 bigram）。"""
    grams = set()
    for i in range(len(text) - 1):
        g = text[i:i + 2]
        if re.fullmatch(r"[\u4e00-\u9fff]{2}", g):
            grams.add(g)
    return grams


def _kw_candidates(kw: str) -> set:
    """英文单词关键词的匹配候选：原词 + 常见单复数变体。

    例：kw="rebuttals" 时 query 里出现 "rebuttal" 也能命中。
    """
    c = {kw}
    if kw.endswith("s"):
        c.add(kw[:-1])
    else:
        c.add(kw + "s")
        c.add(kw + "es")
    return c


# 常见中文动作字（用于"动词首字命中"：query 含触发词的动作字 → 弱信号）
_CN_VERB_CHARS = set(
    "写改润审查搜优监回检提压缩绘设规拆打比转核找调评校验测试编跑修删增补读看"
    "研究探索跟追复投汇总列排分析整理清除扫描备份恢复导出录询部署发布构建译选筛"
)

# 英文"元词"：指代技能体系本身的词（ccfa skills / skill / codex），在 query 中出现
# 只是名词性泛指，不代表任何具体动作，命中无区分度。英文交集计分时剔除。
# 例："用ccfa skills里相应的skill来去ai味" 会让 ccf-skill-forger 靠
# "ccfa/skills/skill" 巧合得 5 分（它是造 skill 的，description 全是这类词），
# 而真正的意图（去 AI 味）对应的 ccf-humanization 只有 2 分。
_LOW_DISC_EN = {"ccfa", "ccf", "skill", "skills", "codex"}

# 英文停用词：query/description 里无区分度的功能词。英文交集计分时剔除——
# 例："search the web for AI funding news" 若不剔除，ccf-literature-searcher 会靠
# description 里的 "for"/"the" 各 +1 而误胜出（researcher 只有 search/web 两个真词）。
_EN_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "use", "using", "used",
    "when", "does", "do", "not", "are", "is", "am", "be", "been", "being", "was",
    "were", "you", "your", "yours", "own", "its", "it", "this", "that", "these",
    "those", "from", "into", "main", "maintain", "maintaining", "only", "full",
    "before", "after", "keep", "keeping", "preserve", "creating", "create",
    "requested", "they", "them", "their", "will", "would", "can", "could", "may",
    "might", "must", "should", "shall", "while", "where", "which", "who", "whom",
    "what", "when", "why", "how", "all", "any", "each", "every", "both", "some",
    "such", "than", "then", "there", "here", "also", "even", "still", "etc", "via",
    "per", "within", "without", "between", "under", "over", "about", "against",
    "during", "among", "toward", "new", "your", "my", "me", "we", "us", "our",
}

# 强意图正则 → 直接命中的 skill。这类短语语义唯一、无歧义，命中即返回，
# 不再参与打分（避免被其他 skill 的巧合命中顶掉）。
_HARD_INTENTS = [
    # 去 AI 味 → ccf-humanization（description: "Humanize and de-defend ... AI-like risk narration"）
    (re.compile(r"去+\s*[aA]+\s*[iI]+\s*味|降\s*[aA]+\s*[iI]+\s*味|去\s*机\s*器\s*味|humaniz\w*", re.IGNORECASE),
     "ccf-humanization"),
]


def match_skill(query: str) -> Optional[Skill]:
    """根据用户提问自动匹配最合适的 skill（打分制，消除短名/关键词歧义）。

    计分规则（按优先级）：
    1. 显式提及：query 中出现 skill 全名 → 按名字长度降序，最先命中的直接胜出
       （"用 literature_reviewer" 必须命中 literature_reviewer，而不是 reviewer）
    2. 强意图短语：命中 _HARD_INTENTS 的唯一语义短语（如"去AI味"→ ccf-humanization）
       → 直接返回对应 skill（前提已注册），不再参与打分
    3. 关键词命中：
       - 中文关键词完整命中 +1（不做模糊的"动词首字"匹配，避免"写一个"靠"写"字误命中）
       - 英文单词 +1（自动匹配单复数变体）；英文多词短语（含空格，如 "code review"）+3
       - 英文元词（ccfa/ccf/skill/skills/codex，_LOW_DISC_EN）命中不计分——
         "用ccfa skills里相应的skill" 是名词性泛指，不是任何具体动作信号
    4. 描述领域词：description 英文单词与 query 英文单词做集合交集（剔除元词），每个 +1；
       中文短语直接子串命中 +2；部分重叠（公共中文 bigram）+1 each（skill 级封顶 +3，
       避免触发词多的 skill 因通用词"论文/检查"系统性占优）
    5. 描述动作动词首字命中（弱信号，封顶 +2）：描述中文短语以动词字开头且该动词字
       出现在 query 中，说明 query 的动作与该 skill 相关。按"动作纯度"加权：
       短语中文部分 ≤3 字（纯动作/动宾短语，如"写作""写代码"）权重 1.0；
       更长短语（动词嵌在复合概念里，如"写作评审""审稿意见回复"）权重 0.5——
       否则"写…论文初稿"时 paper-reviewer 会靠描述里的"写作评审"与 paper-writer
       的"写作"打平，再因名字更长而误胜出。

    家族信号：query 含 "ccf"（如 "ccfa skills"、"CCF-A级别"）说明用户明确要在
    CCFA 技能家族内选择 → 内置 skill 不参与，家族成员各 +1 基础分，阈值升到 2
    （基础分 1 + 至少一个实质信号，避免"ccf 是什么"这类无动作 query 瞎选）。

    总分最高者胜出；同分时内置 skill 优先于 CCFA 家族（内置是默认能力，
    家族 skill 需要明确信号才能抢），再同分取名字更长者，再同分取注册顺序靠前的 skill。
    低于最低阈值（默认 1.0，家族信号下 2.0）返回 None，走默认流程——
    宁可不路由，也不要错误路由（"不匹配任何一个 skill 就别用"）。
    """
    q = query.lower()
    q_en, q_cn = _split_terms(q)
    q_cn_grams = set().union(*[_cn_2grams(p) for p in q_cn]) if q_cn else set()

    # 1) 显式提及：名字最长者优先（literature_reviewer > reviewer）
    named = sorted(_SKILLS.keys(), key=len, reverse=True)
    for name in named:
        if name.lower() in q:
            return _SKILLS[name]

    # 2) 强意图短语：唯一语义，命中即返回
    for pattern, skill_name in _HARD_INTENTS:
        if pattern.search(q) and skill_name in _SKILLS:
            return _SKILLS[skill_name]

    # 家族信号：query 提到 ccf（ccfa skills / CCF-A 级别 / ccf 技能...）
    family = "ccf" in q
    min_score = 2.0 if family else 1.0

    # 3/4/5) 打分制
    best_skill: Optional[Skill] = None
    best_score = 0.0
    for skill in _SKILLS.values():
        # 家族信号下只考虑 CCFA 家族成员（内置 skill 不参与，避免 coder 靠"写一个"抢走）
        if family and not skill.name.startswith("ccf-"):
            continue
        # 家族基础分：用户明确提到 CCFA，家族成员至少 +1
        score = 1.0 if family else 0.0
        # 关键词命中
        for kw in skill.keywords:
            if not kw:
                continue
            if re.search(r"[\u4e00-\u9fff]", kw):
                # 中文关键词：必须完整命中（不做模糊的动词首字匹配）
                if kw in q:
                    score += 1
            elif " " in kw.strip():
                # 英文多词短语（如 "code review"）是强信号，权重更高
                if re.search(rf"(?<![a-zA-Z]){re.escape(kw.strip())}(?![a-zA-Z])", q):
                    score += 3
            else:
                # 单英文词：匹配原词及其单复数变体（元词不计分）
                if kw.lower() not in _LOW_DISC_EN and any(
                    re.search(rf"(?<![a-zA-Z]){re.escape(c)}(?![a-zA-Z])", q)
                    for c in _kw_candidates(kw) if c not in _LOW_DISC_EN
                ):
                    score += 1
        # 描述领域词：英文单词交集（剔除元词与停用词）
        desc = skill.description or ""
        d_en, d_cn = _split_terms(desc)
        score += len(q_en & d_en - _LOW_DISC_EN - _EN_STOPWORDS)
        # 描述中文短语：直接子串 +2；部分重叠（公共 2-gram）+1 each（去重后封顶 +3，
        # 避免触发词多的 skill 因通用词"论文/检查"重复计分而系统性占优）
        all_phrase_grams = set().union(*[_cn_2grams(p) for p in d_cn if p]) if d_cn else set()
        direct_hit = 0
        for phrase in d_cn:
            if not phrase:
                continue
            if phrase in q:
                direct_hit += 1
        score += min(3, direct_hit) * 2 + min(3, len(all_phrase_grams & q_cn_grams))
        # 描述动作动词首字命中：描述中的中文短语若以动词字开头（如"写作"→"写"，
        # "监控"→"监"），且该动词字出现在 query 中，说明 query 的动作与该 skill 相关。
        # 这是区分"写论文→paper-writer"和"追踪论文→literature-monitor"的关键信号。
        # 弱信号，按"动作纯度"加权（封顶 +2）：
        # - 短语中文部分 ≤3 字（纯动作/动宾短语，如"写作""写代码"）→ 权重 1.0
        # - 更长短语（动词嵌在复合概念里，如"写作评审""审稿意见回复"）→ 权重 0.5
        #   否则"写…论文初稿"时 paper-reviewer 会靠描述里的"写作评审"与
        #   paper-writer 的"写作"打平，再因名字更长而误胜出。
        verb_score = 0.0
        for phrase in d_cn:
            if not phrase:
                continue
            first_char = phrase[0]
            if first_char in _CN_VERB_CHARS and first_char in q:
                cn_len = len(re.findall(r"[\u4e00-\u9fff]", phrase))
                verb_score += 1.0 if cn_len <= 3 else 0.5
        score += min(2.0, verb_score)

        # 胜出/平局处理：分数更高胜出；同分时内置 skill 优先于 CCFA 家族，
        # 同类再比名字长度（更具体的 skill 胜出）
        if score > best_score:
            best_score, best_skill = score, skill
        elif score > 0 and score == best_score and best_skill is not None:
            b_family = best_skill.name.startswith("ccf-")
            s_family = skill.name.startswith("ccf-")
            if b_family and not s_family:
                # 内置 skill 优先于 CCFA 家族（如 researcher vs ccf-literature-searcher）
                best_skill = skill
            elif b_family == s_family and len(skill.name) > len(best_skill.name):
                best_skill = skill

    return best_skill if best_score >= min_score else None


def get_skill(name: str) -> Optional[Skill]:
    """Look up a registered skill by name."""
    return _SKILLS.get(name)


def list_skills() -> List[str]:
    """Return names of all registered skills."""
    return list(_SKILLS.keys())


# ---------------------------------------------------------------------------
# Built-in skills
# ---------------------------------------------------------------------------

register_skill(Skill(
    name="coder",
    prompt=(
        "You are an expert software engineer. Write clean, well-tested code. "
        "Use tools to read existing code before making changes. "
        "Always verify your changes compile/run correctly.\n\n"
        "重要规则：在调用 write 或 edit 工具创建/修改文件之前，必须先征求用户同意（如\"我将写入 {path}，可以吗？\"）。"
        "只有用户同意后才执行写入。如果用户没有明确要求写入文件，直接在回复中输出内容即可。"
    ),
    tools=["read", "write", "edit", "bash", "grep", "glob"],
    temperature=0.3,
    description="软件工程/编程/Software Engineering：写代码、修 bug、实现功能、跑测试，write code, implement features, fix bugs",
    keywords=["写代码", "编码", "实现", "修复bug", "debug", "开发", "编程", "写一个", "写个", "program", "implement", "code"],
))

register_skill(Skill(
    name="researcher",
    prompt=(
        "You are a research assistant. Gather information thoroughly, "
        "verify facts from multiple sources, and present findings clearly."
    ),
    tools=["bash", "read", "grep", "glob", "web_search", "tavily_search", "tavily_extract"],
    temperature=0.5,
    description="资料调研/信息收集：查询事实、搜集资料、多源验证",
    keywords=["调研", "查一下", "搜索", "搜索一下", "资料", "信息", "查资料", "research", "search", "搜集",
              "web", "上网查", "上网搜", "搜一下", "找资料", "了解一下"],
))

register_skill(Skill(
    name="reviewer",
    prompt=(
        "You are a senior code reviewer. Focus on bugs, security issues, "
        "performance problems, and readability. Be constructive and specific."
    ),
    tools=["read", "grep", "glob"],
    temperature=0.3,
    description="代码审查/Code Review：审阅代码质量、找 bug、安全/性能问题，review code quality, find bugs, security issues",
    keywords=["review", "审查", "代码评审", "审阅", "code review", "检查代码", "review my code"],
))

register_skill(Skill(
    name="tester",
    prompt=(
        "You are a QA engineer. Write comprehensive tests covering edge cases. "
        "Run tests and fix failures. Aim for high coverage of critical paths."
    ),
    tools=["read", "write", "edit", "bash", "grep", "glob"],
    temperature=0.3,
    description="测试/质量保障：编写并运行单元测试、覆盖边界情况",
    keywords=["测试", "写测试", "单元测试", "test", "testing", "pytest", "unittest"],
))

register_skill(Skill(
    name="literature_reviewer",
    prompt=(
        "你是一位学术综述专家。针对用户给定的主题撰写高质量文献综述。\n\n"
        "**篇幅铁律**：用户明确指定字数（如『800字』）时，全文必须严格控制在要求字数左右（±15%），"
        "宁短勿长，禁止写成远超要求的小作文；用户未指定时默认 800–1200 字。\n\n"
        "执行流程（严格按顺序）：\n"
        "1. **多轮检索**：先用 tavily_search 做至少 2-3 次不同角度的检索（如『主题+综述/评估框架』、『主题+open source/工程实践』、『主题+研究进展』），每次检索后阅读标题/摘要筛选相关文献。\n"
        "2. **结构规划**：在写作前先规划综述结构（概念界定→共识→分歧→展望），随后按结构展开写作。\n"
        "3. **写作要求**：\n"
        "   - 每篇引用必须来自检索结果，禁止编造不存在的论文/数据/引文；检索不到的细节明确标注『未检索到』。\n"
        "   - 结构上避免机械列点，用自然段落推进：先界定概念，再总结共识，接着呈现分歧并分析根源，最后展望未来方向。\n"
        "   - 语言专业、有深度，避免空话套话。\n"
        "   - 若用户限定了字数，段落要精炼：每个要点一句话讲透，不重复、不铺陈。\n"
        "4. **反幻觉自检**：终稿前逐条核对引用是否能在检索结果中找到来源，找不到的立即删除。\n"
        "5. 直接输出综述全文。仅当用户明确要求保存时才调用 write 写入 .md 文件。"
    ),
    tools=["tavily_search", "tavily_extract", "read", "write", "edit", "bash", "grep", "glob"],
    temperature=0.4,
    max_iterations=25,
    description="文献综述/学术综述：围绕主题检索文献并撰写有深度的综述文章",
    keywords=["综述", "文献综述", "review the literature", "literature review", "survey", "研究现状", "进展", "overview", "评述"],
))
