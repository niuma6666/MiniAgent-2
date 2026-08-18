import sys, os
sys.path.insert(0, r"C:\Users\Wang Yuhan\WorkBuddy\2026-08-17-16-30-21\MiniAgent")
os.environ["CCFA_SKILLS_ROOT"] = r"C:\Users\Wang Yuhan\WorkBuddy\2026-08-17-16-30-21\CCFA-Skills"
from miniagent.skills import match_skill
from miniagent.ccfa_loader import load_ccfa_skills
load_ccfa_skills()

queries = [
    "写800字关于在策略自蒸馏的文献综述",
    "写800字关于opd的文献综述",
    "帮我写一篇关于大模型进展的文献综述",
    "写一篇CCF-A级别的论文初稿",
    "帮我审稿这篇论文",
    "帮我写一篇关于图神经网络的可视化论文",
    "帮我优化一下这个研究idea，让它更有创新性",
]
for q in queries:
    s = match_skill(q)
    print(f"{q[:40]:<42} -> {s.name if s else None}")
