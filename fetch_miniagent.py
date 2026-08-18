import json, base64, urllib.request, os

BASE = "https://api.github.com/repos/niuma6666/MiniAgent"
FILES = {
    "miniagent/agent.py": "miniagent/agent.py",
    "miniagent/cli.py": "miniagent/cli.py",
    "miniagent/config.py": "miniagent/config.py",
    "miniagent/logger.py": "miniagent/logger.py",
    "miniagent/memory.py": "miniagent/memory.py",
    "miniagent/skills.py": "miniagent/skills.py",
    "miniagent/__init__.py": "miniagent/__init__.py",
    "miniagent/__main__.py": "miniagent/__main__.py",
    "miniagent/mcp_client.py": "miniagent/mcp_client.py",
    "miniagent/orchestrator.py": "miniagent/orchestrator.py",
    "miniagent/tools/basic_tools.py": "miniagent/tools/basic_tools.py",
    "miniagent/tools/code_tools.py": "miniagent/tools/code_tools.py",
    "miniagent/tools/__init__.py": "miniagent/tools/__init__.py",
    "miniagent/utils/json_utils.py": "miniagent/utils/json_utils.py",
    "miniagent/utils/reflector.py": "miniagent/utils/reflector.py",
    "miniagent/utils/text_utils.py": "miniagent/utils/text_utils.py",
    "miniagent/utils/__init__.py": "miniagent/utils/__init__.py",
    "miniagent/extensions/mcp_client.py": "miniagent/extensions/mcp_client.py",
    "miniagent/extensions/orchestrator.py": "miniagent/extensions/orchestrator.py",
    "miniagent/extensions/__init__.py": "miniagent/extensions/__init__.py",
    "pyproject.toml": "pyproject.toml",
    "requirements.txt": "requirements.txt",
    ".env.example": ".env.example",
    "mcp.json": "mcp.json",
    "AGENTS.md": "AGENTS.md",
    "examples/basic_agent.py": "examples/basic_agent.py",
    "examples/mcp_agent.py": "examples/mcp_agent.py",
    "examples/skill_demo.py": "examples/skill_demo.py",
}

root = r"C:\Users\Wang Yuhan\WorkBuddy\2026-08-17-16-30-21\MiniAgent"
ok, fail = 0, []
for path, dest in FILES.items():
    url = f"{BASE}/contents/{path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MiniAgent-fetch", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        full = os.path.join(root, dest.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        ok += 1
        print(f"OK  {path} ({len(content)}B)")
    except Exception as e:
        fail.append(path)
        print(f"FAIL {path}: {e}")

print(f"\nDownloaded {ok}/{len(FILES)} files, failed: {fail}")
