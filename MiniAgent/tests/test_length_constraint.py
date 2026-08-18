# -*- coding: utf-8 -*-
"""
字数约束测试：用户要求"800字"时，回答必须遵守长度。

覆盖：
1. _extract_length_constraint 解析（800字 / 2000 words / 800个字 / 无要求）
2. _text_length 长度统计（中文按字符、英文按单词）
3. _truncate_to_length 句子边界截断兜底
4. _finalize_response 超长时触发压缩、压缩后仍超长时截断兜底
5. _init_run 把长度要求注入 user message
6. run_with_tools 端到端：超长回答被压缩/截断
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from miniagent.agent import MiniAgent  # noqa: E402

FAKE_KEY = "sk-fake-for-testing"


def make_agent(**kwargs):
    """构造一个不联网、不路由的 MiniAgent（避免依赖真实 LLM/技能）。"""
    agent = MiniAgent(
        model="fake-model",
        api_key=FAKE_KEY,
        base_url="https://fake.invalid/v1",
        auto_route_skills=False,
        **kwargs,
    )
    return agent


class TestExtractLengthConstraint(unittest.TestCase):
    def test_chinese_chars(self):
        a = make_agent()
        self.assertEqual(a._extract_length_constraint("写800字关于OPD的综述"), (800, False))

    def test_chinese_ge(self):
        a = make_agent()
        self.assertEqual(a._extract_length_constraint("写800个字关于OPD的综述"), (800, False))

    def test_english_words(self):
        a = make_agent()
        self.assertEqual(a._extract_length_constraint("write a 500 words summary"), (500, True))

    def test_word_char(self):
        a = make_agent()
        self.assertEqual(a._extract_length_constraint("3000字符的介绍"), (3000, False))

    def test_no_constraint(self):
        a = make_agent()
        self.assertIsNone(a._extract_length_constraint("写一篇关于OPD的综述"))

    def test_too_small_filtered(self):
        a = make_agent()
        self.assertIsNone(a._extract_length_constraint("第2章字数是乱的"))  # 2字太短视为噪音

    def test_year_not_matched(self):
        a = make_agent()
        # "2026年" 不应被误判为长度要求（后面没有"字"）
        self.assertIsNone(a._extract_length_constraint("2026年的研究进展"))


class TestTextLength(unittest.TestCase):
    def test_chinese_counts_no_whitespace(self):
        a = make_agent()
        self.assertEqual(a._text_length("你好 世界", False), 4)
        self.assertEqual(a._text_length("你好，世界！\n第二行", False), 9)

    def test_english_counts_words(self):
        a = make_agent()
        self.assertEqual(a._text_length("hello world foo bar", True), 4)


class TestTruncateToLength(unittest.TestCase):
    def test_short_text_unchanged(self):
        a = make_agent()
        self.assertEqual(a._truncate_to_length("短文本", 100, False), "短文本")

    def test_chinese_sentence_boundary(self):
        a = make_agent()
        text = "第一句。第二句！第三句？第四句；第五句。第六句。第七句。第八句。第九句。第十句。"
        out = a._truncate_to_length(text, 20, False)
        # 20 字正文 + 截断标记（11 字符）
        self.assertLessEqual(a._text_length(out, False), 31)
        self.assertIn("已按字数要求截断", out)
        # 应该在某句结束后截断，而不是中间
        self.assertTrue(out.rstrip().endswith("。") or "…" in out)

    def test_english_words(self):
        a = make_agent()
        text = " ".join(f"word{i}" for i in range(50))
        out = a._truncate_to_length(text, 10, True)
        self.assertLessEqual(len(out.split()), 11)


class TestFinalizeResponse(unittest.TestCase):
    def test_within_limit_no_llm_call(self):
        a = make_agent()
        a._length_constraint = (800, False)
        ok = "短回答。" * 100  # 300 字
        with mock.patch.object(a, "_call_llm") as m:
            out = a._finalize_response(ok, "写800字", [])
        self.assertEqual(out, ok)
        m.assert_not_called()

    def test_over_limit_compresses(self):
        a = make_agent()
        a._length_constraint = (800, False)
        long_text = "这是很长的回答内容。" * 300  # 约 3300 字
        messages = []
        with mock.patch.object(
            a, "_call_llm", return_value="FINAL_ANSWER: 压缩后的精炼回答。"
        ) as m:
            out = a._finalize_response(long_text, "写800字", messages)
        self.assertEqual(out, "压缩后的精炼回答。")
        m.assert_called_once()
        # 压缩请求中应包含待压缩原文
        self.assertIn("待压缩的回答", messages[-1]["content"])
        self.assertIn("800 字", messages[-1]["content"])

    def test_compress_still_over_truncates(self):
        a = make_agent()
        a._length_constraint = (100, False)
        long_text = "超长回答。" * 200
        with mock.patch.object(
            a, "_call_llm", return_value="FINAL_ANSWER: " + "依然很长。" * 100
        ):
            out = a._finalize_response(long_text, "写100字", [])
        # 截断兜底：1.2*100 正文 + 11 字符截断标记，仍在 1.3*100 以内
        self.assertLessEqual(a._text_length(out, False), 131)

    def test_no_constraint_passthrough(self):
        a = make_agent()
        with mock.patch.object(a, "_call_llm") as m:
            out = a._finalize_response("随便多长的回答" * 500, "写综述", [])
        self.assertIn("随便多长", out)
        m.assert_not_called()


class TestInitRunInjectsConstraint(unittest.TestCase):
    def test_user_message_contains_length_rule(self):
        a = make_agent()
        messages, _, _ = a._init_run("写800字关于OPD的综述")
        self.assertEqual(a._length_constraint, (800, False))
        user_msg = messages[-1]["content"]
        self.assertIn("800 字", user_msg)
        self.assertIn("长度要求", user_msg)

    def test_no_constraint_keeps_original(self):
        a = make_agent()
        messages, _, _ = a._init_run("写一篇关于OPD的综述")
        self.assertIsNone(a._length_constraint)
        self.assertEqual(messages[-1]["content"], "写一篇关于OPD的综述")


# ---------------------------------------------------------------------------
# 端到端：run_with_tools 收到超长 FINAL_ANSWER 后应触发压缩（FakeClient）
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


class TestEndToEndCompression(unittest.TestCase):
    def test_overlong_final_answer_gets_compressed(self):
        agent = make_agent()
        long_answer = "FINAL_ANSWER: " + "这是关于OPD蒸馏的详细论述。" * 300  # ~3300字
        agent.client = _FakeClient([
            long_answer,
            "FINAL_ANSWER: 压缩后的约800字综述。",
        ])
        out = agent.run_with_tools("写800字关于OPD的文献综述")
        self.assertEqual(out, "压缩后的约800字综述。")
        # 第二次调用（压缩）应为 temperature=0
        # FakeCompletions 不记录 kwargs，此处主要验证流程不崩且结果被替换

    def test_within_limit_no_second_call(self):
        agent = make_agent()
        short_answer = "FINAL_ANSWER: " + "精炼综述。" * 100  # ~500字
        agent.client = _FakeClient([short_answer])
        out = agent.run_with_tools("写800字关于OPD的文献综述")
        self.assertEqual(out, "精炼综述。" * 100)


if __name__ == "__main__":
    unittest.main()
