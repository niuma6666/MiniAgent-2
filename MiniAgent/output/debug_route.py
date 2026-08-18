"""调试脚本：打印 match_skill 对给定 query 的每个 skill 得分分解。"""
import sys, os, re
sys.path.insert(0, ".")
os.environ["CCFA_SKILLS_ROOT"] = r"C:\Users\Wang Yuhan\WorkBuddy\2026-08-17-16-30-21\CCFA-Skills"

from miniagent.skills import _SKILLS, _split_terms, _cn_2grams, _kw_candidates, _CN_VERB_CHARS
from miniagent.ccfa_loader import load_ccfa_skills

load_ccfa_skills()

QUERY = "数字化转型对资本市场估值效率的影响研究——基于A股上市公司的实证检验，给这个论文写一个大纲，并要求用ccfa skills里相应的skill来去ai味"

q = QUERY.lower()
q_en, q_cn = _split_terms(q)
q_cn_grams = set().union(*[_cn_2grams(p) for p in q_cn]) if q_cn else set()
print("q_en:", q_en)
print("q_cn:", q_cn)
print("q_cn_grams:", sorted(q_cn_grams))
print("=" * 80)

# 显式提及检查
named = sorted(_SKILLS.keys(), key=len, reverse=True)
for name in named:
    if name.lower() in q:
        print(f"!! 显式提及命中: {name}")

rows = []
for skill in _SKILLS.values():
    parts = {}
    score = 0.0

    # 关键词
    kw_score = 0
    kw_hits = []
    for kw in skill.keywords:
        if not kw:
            continue
        if re.search(r"[\u4e00-\u9fff]", kw):
            if kw in q:
                kw_score += 1
                kw_hits.append(f"kw_cn[{kw}]")
        elif " " in kw.strip():
            if re.search(rf"(?<![a-zA-Z]){re.escape(kw.strip())}(?![a-zA-Z])", q):
                kw_score += 3
                kw_hits.append(f"kw_en_phrase[{kw}]")
        else:
            if any(re.search(rf"(?<![a-zA-Z]){re.escape(c)}(?![a-zA-Z])", q) for c in _kw_candidates(kw)):
                kw_score += 1
                kw_hits.append(f"kw_en[{kw}]")
    parts["kw"] = kw_score
    score += kw_score

    desc = skill.description or ""
    d_en, d_cn = _split_terms(desc)
    en_score = len(q_en & d_en)
    en_hits = q_en & d_en
    parts["en"] = en_score
    score += en_score

    all_phrase_grams = set().union(*[_cn_2grams(p) for p in d_cn if p]) if d_cn else set()
    direct_hit = 0
    direct_hits = []
    for phrase in d_cn:
        if not phrase:
            continue
        if phrase in q:
            direct_hit += 1
            direct_hits.append(phrase)
    desc_score = min(3, direct_hit) * 2 + min(3, len(all_phrase_grams & q_cn_grams))
    parts["desc"] = desc_score
    score += desc_score

    verb_score = 0.0
    verb_hits = []
    for phrase in d_cn:
        if not phrase:
            continue
        first_char = phrase[0]
        if first_char in _CN_VERB_CHARS and first_char in q:
            cn_len = len(re.findall(r"[\u4e00-\u9fff]", phrase))
            w = 1.0 if cn_len <= 3 else 0.5
            verb_score += w
            verb_hits.append(f"{phrase}(w={w})")
    v = min(2.0, verb_score)
    parts["verb"] = v
    score += v

    rows.append((score, skill.name, parts, kw_hits, en_hits, direct_hits, verb_hits))

rows.sort(key=lambda r: (-r[0], -len(r[1])))
for score, name, parts, kw_hits, en_hits, direct_hits, verb_hits in rows[:12]:
    print(f"{score:6.2f}  {name:<32} kw={parts['kw']} en={parts['en']} desc={parts['desc']} verb={parts['verb']}")
    if kw_hits or en_hits or direct_hits or verb_hits:
        print(f"         kw: {kw_hits}")
        print(f"         en: {sorted(en_hits)}")
        print(f"         direct: {direct_hits}")
        print(f"         verb: {verb_hits}")
    print()
