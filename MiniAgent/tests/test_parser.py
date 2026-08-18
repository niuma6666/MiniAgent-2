#!/usr/bin/env python3
"""Test tool call parser: handle <TOOL: name> format + multiple calls."""
import sys
sys.path.insert(0, '.')

from miniagent.agent import MiniAgent

# Create a minimal agent instance for testing (no real LLM client)
agent = MiniAgent.__new__(MiniAgent)
agent.tools = [
    {"name": "tavily_search", "description": "search", "parameters": {}, "executor": lambda **k: ""},
    {"name": "write", "description": "write file", "parameters": {}, "executor": lambda **k: ""},
    {"name": "bash", "description": "run cmd", "parameters": {}, "executor": lambda **k: ""},
]

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  OK  {name}")
        passed += 1
    else:
        print(f"  FAIL {name} {detail}")
        failed += 1

print("=== Test 1: <TOOL: name> format with angle brackets ===")
content1 = (
    '<TOOL: tavily_search>\n'
    'ARGS: {"query": "On-Policy Distillation reinforcement learning", "max_results": 8, "search_depth": "advanced"}\n'
    '<TOOL: tavily_search>\n'
    'ARGS: {"query": "on-policy distillation survey", "max_results": 8, "search_depth": "advanced"}'
)
calls1 = agent._parse_all_tool_calls(content1)
check("parses 2 calls", len(calls1) == 2, f"got {len(calls1)}")
if calls1:
    check("first call name", calls1[0]["name"] == "tavily_search")
    check("first call query", calls1[0]["arguments"].get("query", "").startswith("On-Policy"))
if len(calls1) > 1:
    check("second call name", calls1[1]["name"] == "tavily_search")
    check("second call query", calls1[1]["arguments"].get("query", "").startswith("on-policy"))

print("\n=== Test 2: Standard TOOL: format (no angle brackets) ===")
content2 = 'TOOL: tavily_search\nARGS: {"query": "test query", "max_results": 5}'
calls2 = agent._parse_all_tool_calls(content2)
check("parses 1 call", len(calls2) == 1, f"got {len(calls2)}")
if calls2:
    check("correct name", calls2[0]["name"] == "tavily_search")
    check("correct query", calls2[0]["arguments"].get("query") == "test query")

print("\n=== Test 3: 8 batched tool calls (exact user log scenario) ===")
content3 = (
    '<TOOL: tavily_search>\nARGS: {"query": "On-Policy Distillation reinforcement learning", "max_results": 8, "search_depth": "advanced"}\n'
    '<TOOL: tavily_search>\nARGS: {"query": "on-policy distillation survey RL", "max_results": 8, "search_depth": "advanced"}\n'
    '<TOOL: tavily_search>\nARGS: {"query": "knowledge distillation RL review", "max_results": 8}\n'
    '<TOOL: tavily_search>\nARGS: {"query": "on-policy distillation OPD paper arXiv", "max_results": 8}\n'
    '<TOOL: tavily_search>\nARGS: {"query": "on-policy distillation OPD arXiv", "max_results": 8, "search_depth": "advanced"}\n'
    '<TOOL: tavily_search>\nARGS: {"query": "policy distillation vs on-policy teacher student", "max_results": 8}\n'
    '<TOOL: tavily_search>\nARGS: {"query": "distillation in RL survey 2023 2024", "max_results": 8}\n'
    '<TOOL: tavily_search>\nARGS: {"query": "on-policy distillation off-policy mismatch", "max_results": 8, "search_depth": "advanced"}'
)
calls3 = agent._parse_all_tool_calls(content3)
check("parses all 8 calls", len(calls3) == 8, f"got {len(calls3)}")
if len(calls3) == 8:
    check("all are tavily_search", all(c["name"] == "tavily_search" for c in calls3))
    check("each has query", all("query" in c["arguments"] for c in calls3))
    check("4th query correct", calls3[3]["arguments"]["query"].startswith("on-policy distillation OPD paper"))

print("\n=== Test 4: Pure text (no tool calls) ===")
content4 = "FINAL_ANSWER: This is a literature review about OPD..."
calls4 = agent._parse_all_tool_calls(content4)
check("returns empty list", len(calls4) == 0, f"got {len(calls4)}")

print("\n=== Test 5: Backward compat - _parse_tool_call returns first ===")
first = agent._parse_tool_call(content3)
check("returns first call", first is not None)
if first:
    check("correct name", first["name"] == "tavily_search")
    check("correct query", first["arguments"]["query"].startswith("On-Policy"))

print("\n=== Test 6: write tool call ===")
content6 = 'TOOL: write\nARGS: {"path": "review.md", "content": "# Review\\n\\nSome content."}'
calls6 = agent._parse_all_tool_calls(content6)
check("parses write call", len(calls6) == 1, f"got {len(calls6)}")
if calls6:
    check("correct name", calls6[0]["name"] == "write")
    check("correct path", calls6[0]["arguments"].get("path") == "review.md")

print("\n=== Test 7: Mixed text + tool calls (model explains then calls) ===")
content7 = (
    "I'll search for information about OPD first.\n\n"
    '<TOOL: tavily_search>\n'
    'ARGS: {"query": "on-policy distillation", "max_results": 5}'
)
calls7 = agent._parse_all_tool_calls(content7)
check("finds 1 call among text", len(calls7) == 1, f"got {len(calls7)}")
if calls7:
    check("correct name", calls7[0]["name"] == "tavily_search")

print(f"\n=== Results: {passed} passed, {failed} failed ===")

print("\n=== Test 8: Windows path with raw backslashes (invalid JSON escapes) ===")
content8 = '<TOOL: write>\nARGS: {"path": "D:\Internet\Temp\out.md", "content": "x"}'
calls8 = agent._parse_all_tool_calls(content8)
check("parses write with windows path", len(calls8) == 1, f"got {len(calls8)}")
if calls8:
    check("name is write", calls8[0]["name"] == "write")
    check("path preserved", calls8[0]["arguments"].get("path") == "D:\Internet\Temp\out.md",
          f"got {calls8[0]['arguments'].get('path')!r}")

print("\n=== Test 9: escaped backslashes still work (no double-escaping) ===")
content9 = '<TOOL: write>\nARGS: {"path": "D:\\Folder\\file.txt", "content": "y"}'
calls9 = agent._parse_all_tool_calls(content9)
check("parses escaped path", len(calls9) == 1, f"got {len(calls9)}")
if calls9:
    check("path preserved", calls9[0]["arguments"].get("path") == "D:\Folder\file.txt",
          f"got {calls9[0]['arguments'].get('path')!r}")

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(1 if failed else 0)
