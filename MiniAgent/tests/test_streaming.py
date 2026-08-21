# -*- coding: utf-8 -*-
"""
流式输出修复的回归测试。

覆盖本次修复的四个行为：
A. _create_stream_response 创建阶段失败自动重试（@retry 必须挂在普通函数上，
   挂生成器函数无效——迭代中的异常不会被捕获）
B. run_with_tools 流式失败自动降级为非流式（保证"流式挂了也一定有回答"）
C. stream_callback 每轮 LLM 调用前被 reset（工具调用之后最终答案继续流式打印）
D. 停滞看门狗：超过 LLM_STREAM_STALL_TIMEOUT 无数据 → 中止，不无限挂起
"""
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tenacity import RetryError  # noqa: E402

from miniagent.agent import MiniAgent  # noqa: E402

FAKE_KEY = "sk-fake-for-testing"


# ---------------------------------------------------------------------------
# Fake LLM client：stream=True 返回可迭代的 chunk，否则返回普通响应
# ---------------------------------------------------------------------------
class _Delta:
    def __init__(self, content: str):
        self.content = content


class _Choice:
    def __init__(self, delta):
        self.delta = delta


class _Chunk:
    def __init__(self, content: str):
        self.choices = [_Choice(_Delta(content))]


class _Message:
    def __init__(self, content: str):
        self.content = content


class _RespChoice:
    def __init__(self, content: str):
        self.message = _Message(content)


class _Response:
    def __init__(self, content: str):
        self.choices = [_RespChoice(content)]


class _FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        text = self._responses.pop(0) if self._responses else "FINAL_ANSWER: (empty)"
        if kwargs.get("stream"):
            return [_Chunk(text)]
        return _Response(text)


class _FakeChat:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)


class _FakeClient:
    def __init__(self, responses):
        self.chat = _FakeChat(responses)


def make_agent(responses, **kwargs):
    """构造一个替换了 LLM 客户端的 MiniAgent（关闭技能路由，聚焦流式路径）。"""
    agent = MiniAgent(
        model="fake-model",
        api_key=FAKE_KEY,
        base_url="https://fake.invalid/v1",
        llm_route_skills=False,
        auto_route_skills=False,
        **kwargs,
    )
    agent.client = _FakeClient(responses)
    # 关闭重试等待，让测试不 sleep（tenacity 装饰器把 Retrying 挂在 .retry 上）
    agent._create_stream_response.retry.sleep = lambda secs: None
    return agent


class TestStreamCreationRetry(unittest.TestCase):
    """A：创建阶段失败自动重试。"""

    def test_create_stream_response_retries_until_success(self):
        agent = make_agent([])
        calls = {"n": 0}

        def flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] < 3:  # 前两次失败（如 5xx/overloaded），第三次成功
                raise RuntimeError("provider overloaded")
            return [_Chunk("ok")]

        agent.client.chat.completions.create = flaky

        result = agent._create_stream_response([{"role": "user", "content": "hi"}])
        self.assertEqual(calls["n"], 3, "应重试 2 次后成功")
        self.assertEqual(result[0].choices[0].delta.content, "ok")

    def test_create_stream_response_gives_up_after_3(self):
        agent = make_agent([])

        def always_fail(**kwargs):
            raise RuntimeError("boom")

        agent.client.chat.completions.create = always_fail

        with self.assertRaises(RetryError):
            agent._create_stream_response([{"role": "user", "content": "hi"}])


class TestStreamFallback(unittest.TestCase):
    """B：run_with_tools 流式失败 → 降级为非流式，仍有回答。"""

    def test_run_with_tools_falls_back_to_non_stream(self):
        agent = make_agent(["FINAL_ANSWER: 降级回答成功。"])
        real_create = agent.client.chat.completions.create

        def flaky(**kwargs):
            if kwargs.get("stream"):
                raise RuntimeError("stream broken")
            return real_create(**kwargs)

        agent.client.chat.completions.create = flaky

        tokens = []
        result = agent.run_with_tools("你好", max_iterations=2, stream_callback=tokens.append)

        self.assertIn("降级回答成功", result, "流式失败后应降级为非流式并给出回答")
        self.assertEqual(tokens, [], "流式全程失败，不应有任何 token")


class TestStreamCallbackReset(unittest.TestCase):
    """C：每轮 LLM 调用前 reset → 工具调用之后最终答案继续流式打印。"""

    def test_callback_reset_after_tool_call_iteration(self):
        agent = make_agent([
            "<TOOL: read>\nARGS: {\"path\": \"a.txt\"}",
            "FINAL_ANSWER: 最终答案。",
        ])
        agent.load_builtin_tool("read")

        resets = []
        printed = []

        class Printer:
            def __init__(self):
                self.chunks = []
                self.has_tool_call = False

            def reset(self):
                resets.append(len(self.chunks))
                self.chunks = []
                self.has_tool_call = False

            def __call__(self, token):
                self.chunks.append(token)
                partial = "".join(self.chunks)
                if "TOOL:" in partial or "Tool:" in partial or "工具:" in partial:
                    self.has_tool_call = True
                    return
                if not self.has_tool_call:
                    printed.append(token)

        printer = Printer()
        result = agent.run_with_tools("读文件", max_iterations=3, stream_callback=printer)

        # 两次 LLM 调用（工具轮 + 最终答案轮）→ 每轮开始前各 reset 一次
        self.assertEqual(len(resets), 2, f"应有 2 次 reset，实际 {len(resets)}: {resets}")
        # 第二轮（最终答案）的 token 被打印出来了（旧实现会永久哑火）
        self.assertIn("最终答案", "".join(printed))
        self.assertIn("最终答案", result)


class TestStreamWatchdog(unittest.TestCase):
    """D：停滞看门狗——服务端停发数据时中止，不无限挂起。"""

    def test_stall_aborts_stream(self):
        agent = make_agent([])

        class _BlockingStream:
            """模拟服务端停发数据：__next__ 阻塞，直到被 close() 唤醒。"""

            def __init__(self):
                self._closed = False
                self._evt = threading.Event()

            def __iter__(self):
                return self

            def __next__(self):
                self._evt.wait(30)
                if self._closed:
                    raise RuntimeError("stream closed by watchdog")
                raise StopIteration

            def close(self):
                self._closed = True
                self._evt.set()

        agent.client.chat.completions.create = lambda **kw: _BlockingStream()

        with mock.patch.dict(os.environ, {"LLM_STREAM_STALL_TIMEOUT": "1"}):
            gen = agent._call_llm_stream([{"role": "user", "content": "hi"}])
            started = time.monotonic()
            with self.assertRaises(Exception):
                for _ in gen:
                    pass
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 10, f"看门狗应在数秒内中止停滞流，实际耗时 {elapsed:.1f}s")


class TestStreamFallbackReset(unittest.TestCase):
    """A2：流式中途失败降级时，回调累积状态被重置，完整回答不被吞。"""

    def test_fallback_resets_stream_callback(self):
        agent = make_agent(["FINAL_ANSWER: 完整降级答案。"])
        agent._create_stream_response.retry.sleep = lambda secs: None

        class _FailingStream:
            """先吐出 2 个 token，随后断流。"""

            def __init__(self):
                self._chunks = [_Chunk("前半"), _Chunk("段答")]
                self._closed = False

            def __iter__(self):
                return self

            def __next__(self):
                if self._chunks:
                    return self._chunks.pop(0)
                raise RuntimeError("connection reset mid-stream")

            def close(self):
                self._closed = True

        real_create = agent.client.chat.completions.create

        def flaky(**kwargs):
            if kwargs.get("stream"):
                return _FailingStream()
            return real_create(**kwargs)

        agent.client.chat.completions.create = flaky

        tokens = []
        resets = []

        class Printer:
            def __init__(self):
                self.chunks = []

            def reset(self):
                resets.append(True)
                self.chunks = []

            def __call__(self, token):
                self.chunks.append(token)
                tokens.append(token)

        printer = Printer()
        result = agent.run_with_tools("你好", max_iterations=2, stream_callback=printer)

        # 流式先输出了部分 token
        self.assertEqual(tokens, ["前半", "段答"])
        # 降级后必须重置回调累积状态（否则 CLI 会误判"已流式打印"而吞掉完整回答）
        self.assertGreaterEqual(len(resets), 1, "降级后应重置回调累积状态")
        # 完整回答仍然返回
        self.assertIn("完整降级答案", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
