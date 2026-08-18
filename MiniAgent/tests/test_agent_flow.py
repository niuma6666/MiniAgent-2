# -*- coding: utf-8 -*-
"""
端到端流程测试：mock LLM，验证 MiniAgent 在真实 run 循环里的行为。

覆盖用户实际报告的问题：
A. `<TOOL: name>\nARGS: {...}` 尖括号格式解析
B. 模型一次输出多个 TOOL 块 → 全部执行（不再只取第一个）
C. 自动路由：文献综述类 query 正确路由到 literature_reviewer
D. write/edit 文件写入必须先征求用户同意（默认开启硬确认）
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from miniagent.agent import MiniAgent  # noqa: E402

FAKE_KEY = "sk-fake-for-testing"


# ---------------------------------------------------------------------------
# Fake LLM client：只暴露 run_with_tools 需要的 chat.completions.create
# ---------------------------------------------------------------------------
class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        content = self._responses.pop(0) if self._responses else "FINAL_ANSWER: (empty)"
        return _FakeResponse(content)


class _FakeChat:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)


class _FakeClient:
    def __init__(self, responses):
        self.chat = _FakeChat(responses)


def make_agent(responses, **kwargs):
    """构造一个替换了 LLM 客户端的 MiniAgent。"""
    agent = MiniAgent(
        model="fake-model",
        api_key=FAKE_KEY,
        base_url="https://fake.invalid/v1",
        **kwargs,
    )
    agent.client = _FakeClient(responses)
    return agent


class TestMultiToolExecution(unittest.TestCase):
    """问题 A+B：尖括号格式 + 多工具调用全部执行。"""

    def test_multiple_tools_all_executed(self):
        agent = make_agent([
            # 第一轮：deepseek-v4-flash 风格，2 个带尖括号的 TOOL 块
            "<TOOL: read>\nARGS: {\"path\": \"a.txt\"}\n\n"
            "<TOOL: read>\nARGS: {\"path\": \"b.txt\"}",
            # 第二轮：直接给最终答案
            "FINAL_ANSWER: 两轮搜索完成。",
        ], llm_route_skills=False)
        agent.load_builtin_tool("read")

        events = []

        def cb(phase, name, payload):
            events.append((phase, name, payload))

        result = agent.run_with_tools("读两个文件", max_iterations=3, tool_callback=cb)

        starts = [e for e in events if e[0] == "start"]
        self.assertEqual(len(starts), 2, f"应有 2 个工具执行，实际 {len(starts)}: {starts}")
        paths = [e[2]["arguments"]["path"] for e in starts]
        self.assertEqual(paths, ["a.txt", "b.txt"])
        self.assertIn("两轮搜索完成", result)

    def test_standard_parser_backward_compat(self):
        """旧格式 TOOL: name ARGS: {...} 仍可用。"""
        agent = make_agent([
            "TOOL: read ARGS: {\"path\": \"c.txt\"}",
            "FINAL_ANSWER: 完成",
        ], llm_route_skills=False)
        agent.load_builtin_tool("read")

        events = []

        def cb(phase, name, payload):
            events.append((phase, name, payload))

        agent.run_with_tools("读文件", max_iterations=3, tool_callback=cb)
        starts = [e for e in events if e[0] == "start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0][2]["arguments"]["path"], "c.txt")


class TestFileWriteConfirmation(unittest.TestCase):
    """问题 D：write/edit 必须先征求用户同意。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="miniagent_test_")
        self.target = os.path.join(self.tmpdir, "out.md")

    def tearDown(self):
        if os.path.exists(self.target):
            os.remove(self.target)
        os.rmdir(self.tmpdir)

    def test_write_rejected_when_user_says_no(self):
        confirmations = []

        def confirm(desc):
            confirmations.append(desc)
            return False  # 用户拒绝

        agent = make_agent([
            f"<TOOL: write>\nARGS: {{\"path\": \"{self.target}\", \"content\": \"secret\"}}",
            "FINAL_ANSWER: 用户拒绝了写入。",
        ], confirm_file_writes=True, confirm_callback=confirm, llm_route_skills=False)
        agent.load_builtin_tool("write")

        result = agent.run_with_tools("帮我写个文件", max_iterations=3)

        # 确认回调被调用，且描述包含要写的路径
        self.assertEqual(len(confirmations), 1)
        self.assertIn("写入文件", confirmations[0])
        self.assertIn(self.target, confirmations[0])
        # 文件未被创建
        self.assertFalse(os.path.exists(self.target), "用户拒绝后文件不应被创建")
        self.assertIn("用户拒绝了写入", result)

    def test_write_allowed_when_user_says_yes(self):
        def confirm(desc):
            return True  # 用户同意

        agent = make_agent([
            f"<TOOL: write>\nARGS: {{\"path\": \"{self.target}\", \"content\": \"hello\"}}",
            "FINAL_ANSWER: 写入完成。",
        ], confirm_file_writes=True, confirm_callback=confirm, llm_route_skills=False)
        agent.load_builtin_tool("write")

        agent.run_with_tools("帮我写个文件", max_iterations=3)

        self.assertTrue(os.path.exists(self.target), "用户同意后文件应被创建")
        with open(self.target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "hello")

    def test_write_confirmation_can_be_disabled(self):
        """confirm_file_writes=False 时不再确认（无人值守场景）。"""
        confirm_called = []

        def confirm(desc):
            confirm_called.append(desc)
            return True

        agent = make_agent([
            f"<TOOL: write>\nARGS: {{\"path\": \"{self.target}\", \"content\": \"auto\"}}",
            "FINAL_ANSWER: 完成。",
        ], confirm_file_writes=False, confirm_callback=confirm, llm_route_skills=False)
        agent.load_builtin_tool("write")
        agent.run_with_tools("帮我写个文件", max_iterations=3)

        self.assertEqual(confirm_called, [], "关闭确认后不应弹确认")
        self.assertTrue(os.path.exists(self.target))

    def test_default_stdin_reject_on_eof(self):
        """未注入回调时走 stdin；EOF（无人值守）→ 默认拒绝。"""
        agent = make_agent([
            f"<TOOL: write>\nARGS: {{\"path\": \"{self.target}\", \"content\": \"x\"}}",
            "FINAL_ANSWER: 已拒绝。",
        ], confirm_file_writes=True, llm_route_skills=False)
        agent.load_builtin_tool("write")

        with mock.patch("builtins.input", side_effect=EOFError):
            result = agent.run_with_tools("帮我写个文件", max_iterations=3)

        self.assertFalse(os.path.exists(self.target))
        self.assertIn("已拒绝", result)


class TestAutoRouting(unittest.TestCase):
    """问题 C：文献综述 query 应路由到 literature_reviewer 而非 coder。

    本类用 llm_route_skills=False 显式走评分系统链路，验证"评分兜底"仍正确。
    LLM 路由（默认开启）的行为由 TestLLMRouting 覆盖。
    """

    def test_literature_review_query_routes_to_literature_reviewer(self):
        agent = make_agent([
            "FINAL_ANSWER: 这是文献综述正文……",
        ], llm_route_skills=False)
        agent.run("写800字关于在策略自蒸馏的文献综述", max_iterations=2)

        self.assertIsNotNone(agent._loaded_skill)
        self.assertEqual(agent._loaded_skill.name, "literature_reviewer")

    def test_coding_query_routes_to_coder(self):
        agent = make_agent([
            "FINAL_ANSWER: 快速排序代码……",
        ], llm_route_skills=False)
        agent.run("写一个快速排序算法", max_iterations=2)

        self.assertIsNotNone(agent._loaded_skill)
        self.assertEqual(agent._loaded_skill.name, "coder")

    def test_skill_prompt_injected_into_system(self):
        """路由后 system prompt 应包含 skill 的完整指引。"""
        agent = make_agent([
            "FINAL_ANSWER: 综述。",
        ], llm_route_skills=False)
        agent.run("帮我写一篇关于大模型进展的文献综述", max_iterations=2)

        system_prompt = agent._build_dynamic_system_prompt(mode="text")
        self.assertIn(agent._loaded_skill.prompt, system_prompt)
        # 文件写入安全规则必须出现在提示词里（英文模板或中文 skill prompt）
        self.assertTrue(
            "File writing safety" in system_prompt or "征求" in system_prompt,
            "系统提示词应包含文件写入安全规则",
        )


class TestLLMRouting(unittest.TestCase):
    """LLM 路由（默认开启）：把 skill 列表 + 用户问题交给模型决策。

    模型决策被尊重；只有调用失败/无法解析时才回退评分系统。
    """

    @classmethod
    def setUpClass(cls):
        # CCFA skills 目录：MiniAgent/../CCFA-Skills（供 ccf-humanization 用例使用）
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ccfa_root = os.path.join(os.path.dirname(repo_root), "CCFA-Skills")
        cls.has_ccfa = os.path.isdir(ccfa_root)
        if cls.has_ccfa:
            os.environ["CCFA_SKILLS_ROOT"] = ccfa_root

    def test_llm_picks_humanization_for_user_query(self):
        """用户原始 query：模型（FakeClient 模拟）选 ccf-humanization → 尊重。"""
        if not self.has_ccfa:
            self.skipTest("CCFA-Skills 目录不存在")
        agent = make_agent([
            "SKILL: ccf-humanization",
            "FINAL_ANSWER: 大纲已按去AI味规则撰写。",
        ])
        agent.run(
            "数字化转型对资本市场估值效率的影响研究——基于A股上市公司的实证检验，"
            "给这个论文写一个大纲，并用ccfa skills里相应的skill来去ai味",
            max_iterations=2,
        )
        self.assertIsNotNone(agent._loaded_skill)
        self.assertEqual(agent._loaded_skill.name, "ccf-humanization")

    def test_llm_says_none_is_respected(self):
        """模型明确说 none → 不路由（即使评分系统会给 coder 高分）。"""
        agent = make_agent([
            "SKILL: none",
            "FINAL_ANSWER: 好的。",
        ])
        agent.run("写一个快速排序算法", max_iterations=2)
        self.assertIsNone(agent._loaded_skill, "模型说 none 时应尊重，不硬路由到 coder")

    def test_llm_unparseable_falls_back_to_scoring(self):
        """模型回答无法解析 → 回退评分系统 → coder。"""
        agent = make_agent([
            "I think this is a coding task but let me not commit to a skill name.",
            "FINAL_ANSWER: 好的。",
        ])
        agent.run("写一个快速排序算法", max_iterations=2)
        self.assertIsNotNone(agent._loaded_skill)
        self.assertEqual(agent._loaded_skill.name, "coder")

    def test_llm_error_falls_back_to_scoring(self):
        """LLM 路由调用抛异常 → 回退评分系统 → coder。"""
        agent = make_agent([
            "FINAL_ANSWER: 好的。",
        ])
        real_call = agent._call_llm
        calls = {"n": 0}

        def flaky(messages, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:  # 只有路由这次调用失败
                raise RuntimeError("api down")
            return real_call(messages, **kwargs)

        with mock.patch.object(agent, "_call_llm", side_effect=flaky):
            agent.run("写一个快速排序算法", max_iterations=2)
        self.assertIsNotNone(agent._loaded_skill)
        self.assertEqual(agent._loaded_skill.name, "coder")


if __name__ == "__main__":
    unittest.main(verbosity=2)
