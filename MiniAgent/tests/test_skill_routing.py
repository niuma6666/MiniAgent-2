"""skill 自动路由回归测试。

覆盖：内置 5 skill + CCFA 17 skill（需设置 CCFA_SKILLS_ROOT 环境变量）。
重点验证历史 bug 用例：
- '运用literature_reviewer的skill...' 必须命中 literature_reviewer 而非 reviewer
- 'review this code' 必须命中 reviewer 而非 coder
- '写一篇论文初稿' 必须命中 ccf-paper-writer 而非 ccf-literature-monitor
- '帮我审稿这篇论文' 必须命中 ccf-paper-reviewer 而非内置 reviewer

运行：
    python tests/test_skill_routing.py                # 仅内置
    CCFA_SKILLS_ROOT=... python tests/test_skill_routing.py   # 内置 + CCFA
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from miniagent.skills import match_skill  # noqa: E402

BUILTIN_CASES = [
    # (query, expected_skill_name | None)
    ("运用literature_reviewer的skill，写800字关于deepseek harness的综述", "literature_reviewer"),
    ("帮我写一篇关于大模型进展的文献综述", "literature_reviewer"),
    ("give me a survey of LLM agents", "literature_reviewer"),
    ("review this code in src/auth.py", "reviewer"),
    ("write me a code review of auth.py", "reviewer"),
    ("写一个快速排序算法", "coder"),
    ("implement a sorting function", "coder"),
    ("帮我搜索一下2024年AI融资情况", "researcher"),
    ("search the web for AI funding news", "researcher"),
    ("给这个模块写单元测试", "tester"),
    ("今天天气怎么样", None),
]

CCFA_CASES = [
    ("帮我优化一下这个研究idea，让它更有创新性", "ccf-idea-optimizer"),
    ("写一篇CCF-A级别的论文初稿", "ccf-paper-writer"),
    ("帮我写一篇关于图神经网络的可视化论文", "ccf-paper-writer"),
    ("帮我审稿这篇论文，给出review意见", "ccf-paper-reviewer"),
    ("帮我审稿这篇论文", "ccf-paper-reviewer"),  # 无英文关键词时也不能被 rebuttal-writer 抢走
    ("写rebuttal回复审稿人意见", "ccf-rebuttal-writer"),
    ("帮我做一下论文投稿检查", "ccf-submission-checker"),
    ("帮我把这段论文去去AI味", "ccf-humanization"),
    ("帮我追踪一下这个方向有没有新论文", "ccf-literature-monitor"),
    ("帮我搜一下这个方向的相关工作", "ccf-literature-searcher"),
    ("帮我检查论文实验设计的合理性", "ccf-experiment-designer"),
    # 家族信号：query 提到 ccfa skills → 只在 CCFA 家族内选（内置 coder 不得参与），
    # "去ai味"强意图 → ccf-humanization（不能被 skill-forger 靠 "skills/skill" 元词抢走）
    ("数字化转型对资本市场估值效率的影响研究——基于A股上市公司的实证检验，给这个论文写一个大纲，并要求用ccfa skills里相应的skill来去ai味", "ccf-humanization"),
    # 内置 skill 不应被 CCFA 抢占
    ("review this code in src/auth.py", "reviewer"),
    ("帮我写一篇关于大模型进展的文献综述", "literature_reviewer"),
    ("写一个快速排序算法", "coder"),
    # CCFA 加载后内置 researcher 不能被 ccf-humanization / ccf-literature-searcher 靠 "ai"/"search" 平局抢走
    ("帮我搜索一下2024年AI融资情况", "researcher"),
    ("search the web for AI funding news", "researcher"),
    # 家族信号但无实质动作意图 → 低于阈值，不路由
    ("ccfa的skill有哪些", None),
]


def run(cases, label: str) -> int:
    ok = 0
    for query, expected in cases:
        skill = match_skill(query)
        got = skill.name if skill else None
        if got == expected:
            ok += 1
            print(f"OK   {query[:44]:<46} -> {got}")
        else:
            print(f"FAIL {query[:44]:<46} -> {got} (期望 {expected})")
    print(f"--- {label}: {ok}/{len(cases)} ---")
    return ok


def main() -> int:
    total_ok = run(BUILTIN_CASES, "内置 skills")
    ccfa_root = os.environ.get("CCFA_SKILLS_ROOT")
    if ccfa_root:
        from miniagent.ccfa_loader import load_ccfa_skills
        load_ccfa_skills(ccfa_root)
        total_ok += run(CCFA_CASES, "CCFA skills")
    else:
        print("(未设置 CCFA_SKILLS_ROOT，跳过 CCFA 用例)")
    return 0 if total_ok == len(BUILTIN_CASES) + (len(CCFA_CASES) if ccfa_root else 0) else 1


if __name__ == "__main__":
    sys.exit(main())
