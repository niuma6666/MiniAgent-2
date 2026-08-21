# -*- coding: utf-8 -*-
"""
native（Function Calling）模式回归测试。

覆盖修复：native 模式消息历史必须统一为 dict——此前直接把 openai 的
ChatCompletionMessage（pydantic 对象）append 进 messages，_summarize_messages
的 .get("role")/.get("content") 在上下文压缩时会 AttributeError 崩溃
（长任务 + MAX_CONTEXT_MESSAGES 触达时必现）。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from miniagent.agent import MiniAgent  # noqa: E402

FAKE_KEY = "sk-fake-for-testing"


class _FakeMsg:
    def __init__(self, content: str, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeChoice:
    def __init__(self, msg):
        self.message = msg


class _FakeResponse:
    def __init__(self, msg):
        self.choices = [_FakeChoice(msg)]


class _FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        content = self._responses.pop(0) if self._responses else "FINAL_ANSWER: (empty)"
        return _FakeResponse(_FakeMsg(content))


class _FakeChat:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)


class _FakeClient:
    def __init__(self, responses):
        self.chat = _FakeChat(responses)


class _FakeToolCallFunction:
    """模拟 openai ChatCompletionMessageToolCall.function。"""
    name = "bash"
    arguments = '{"cmd": "ls"}'


class _FakeToolCall:
    """模拟 openai ChatCompletionMessageToolCall。"""
    id = "call_1"
    type = "function"
    function = _FakeToolCallFunction()


class TestNativeModeDictMessages(unittest.TestCase):
    """native 模式消息必须统一为 dict，上下文压缩不崩溃。"""

    def test_compression_does_not_crash(self):
        agent = MiniAgent(
            model="fake-model",
            api_key=FAKE_KEY,
            base_url="https://fake.invalid/v1",
            llm_route_skills=False,
            auto_route_skills=False,
        )
        # 连续 7 条短回复（触发"不完整→继续"循环），最后给最终答案。
        # 每轮 +2 条消息，配合 MAX_CONTEXT_MESSAGES=10 会在第 6-7 轮触发
        # _summarize_messages 的遍历路径（len > keep_last+2=12）——
        # 旧实现此处对 _FakeMsg 调 .get() 直接 AttributeError。
        responses = ["嗯"] * 7 + ["FINAL_ANSWER: 压缩后完成。"]
        agent.client = _FakeClient(responses)

        with mock.patch.dict(os.environ, {"MAX_CONTEXT_MESSAGES": "10"}):
            result = agent.run_with_native_tools("你好", max_iterations=8)

        self.assertIn("压缩后完成", result)

    def test_message_to_dict_preserves_tool_calls(self):
        """_message_to_dict 应保留 tool_calls（assistant 消息带工具调用）。"""
        agent = MiniAgent(
            model="fake-model",
            api_key=FAKE_KEY,
            base_url="https://fake.invalid/v1",
            llm_route_skills=False,
            auto_route_skills=False,
        )

        msg = _FakeMsg("", tool_calls=[_FakeToolCall()])
        d = agent._message_to_dict(msg)
        self.assertEqual(d["role"], "assistant")
        self.assertEqual(d["content"], "")
        self.assertEqual(d["tool_calls"][0]["id"], "call_1")
        self.assertEqual(d["tool_calls"][0]["function"]["name"], "bash")
        self.assertEqual(d["tool_calls"][0]["function"]["arguments"], '{"cmd": "ls"}')


if __name__ == "__main__":
    unittest.main(verbosity=2)
