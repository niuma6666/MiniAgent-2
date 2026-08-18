import json, base64, urllib.request, os

BASE = "https://api.github.com/repos/mikubaka88/CCFA-Skills"
FILES = [
    "ccf-common/SKILL.md",
    "ccf-common/references/routing.md",
    "ccf-common/references/skill-trigger-registry.yaml",
    "ccf-paper-writer/SKILL.md",
    "ccf-pipeline-orchestrator/SKILL.md",
    "ccf-literature-searcher/SKILL.md",
    "ccf-idea-optimizer/SKILL.md",
    "AGENT_GUIDE.md",
    "README.zh-CN.md",
]

root = r"C:\Users\Wang Yuhan\WorkBuddy\2026-08-17-16-30-21\CCFA-Skills"
ok, fail = 0, []
for path in FILES:
    url = f"{BASE}/contents/{path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MiniAgent-fetch", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        full = os.path.join(root, path.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        ok += 1
        print(f"OK  {path} ({len(content)}B)")
    except Exception as e:
        fail.append(path)
        print(f"FAIL {path}: {e}")

print(f"\nDownloaded {ok}/{len(FILES)} files, failed: {fail}")
