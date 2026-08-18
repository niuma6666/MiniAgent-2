import sys, os
sys.path.insert(0, ".")
os.environ["CCFA_SKILLS_ROOT"] = r"C:\Users\Wang Yuhan\WorkBuddy\2026-08-17-16-30-21\CCFA-Skills"
from miniagent.ccfa_loader import load_ccfa_skills
load_ccfa_skills()
from miniagent.skills import _SKILLS

lines = []
for name, skill in sorted(_SKILLS.items(), key=lambda kv: kv[0]):
    desc = (skill.description or "").replace("\n", " ").strip()
    if len(desc) > 160:
        desc = desc[:160] + "…"
    line = f"- {name}: {desc}"
    if skill.keywords:
        line += f" | keywords: {', '.join(skill.keywords[:8])}"
    lines.append(line)
print(f"共 {len(_SKILLS)} 个 skill\n")
print("\n".join(lines))
