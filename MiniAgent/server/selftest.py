"""MiniAgent Web 服务自检脚本（B1：回归固化）。

用法（在 MiniAgent/ 目录下）：
    .venv\\Scripts\\python server/selftest.py                # standalone + E2E（需服务器运行）
    .venv\\Scripts\\python server/selftest.py --standalone   # 只跑不依赖服务器的单测
    .venv\\Scripts\\python server/selftest.py --uri ws://127.0.0.1:8000/ws

说明：
- standalone 部分不依赖服务器、不消耗 API；
- E2E 部分会真实调用 LLM（消耗 API 额度），并写临时文件验证确认桥；
- E2E 在服务器不可达时自动跳过（SKIP）。
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
import threading
import time

# 保证能从任意 cwd 找到 server 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets  # noqa: E402

import server.session as S  # noqa: E402

RESULTS = []


def record(name, status, detail=""):
    RESULTS.append((name, status, detail))
    print(f"[{status}] {name} {detail}")


# ============================================================
# standalone（不依赖服务器）
# ============================================================

def test_build_query_format():
    h = [{"role": "user", "content": "第一问"}, {"role": "assistant", "content": "第一答"}]
    q = S.build_query(h, "第二问")
    assert "Conversation history (most recent last):" in q, q
    assert "user: 第一问" in q and "assistant: 第一答" in q, q
    assert q.rstrip().endswith("第二问"), q
    # 无历史时原样返回
    assert S.build_query([], "直接问") == "直接问"


async def test_confirm_timeout():
    old = os.environ.get("CONFIRM_TIMEOUT")
    os.environ["CONFIRM_TIMEOUT"] = "2"
    try:
        s = S.Session("timeout-test")
        result = {}
        th = threading.Thread(
            target=lambda: result.setdefault("v", s.confirm_callback("写入文件 x")))
        t0 = time.monotonic()
        th.start()
        while th.is_alive():
            await asyncio.sleep(0.05)
        elapsed = time.monotonic() - t0
        assert result.get("v") is False, "超时应返回 False（拒绝）"
        assert 1.0 <= elapsed <= 6, f"应约 2s 超时，实际 {elapsed:.1f}s"
    finally:
        if old is None:
            os.environ.pop("CONFIRM_TIMEOUT", None)
        else:
            os.environ["CONFIRM_TIMEOUT"] = old


async def test_build_failure_pushes_error():
    s = S.Session("a1-test")
    original = S.build_agent

    def boom(confirm_callback=None):
        raise RuntimeError("simulated build failure")

    S.build_agent = boom
    try:
        events = []
        th = threading.Thread(target=s.run_agent, args=("hi",))
        th.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            while not s.aqueue.empty():
                events.append(s.aqueue.get_nowait())
            if not th.is_alive():
                break
        th.join(timeout=2)
        assert events and events[-1]["type"] == "error", events
        assert "初始化失败" in events[-1]["message"]
        assert s._running is False
    finally:
        S.build_agent = original


async def test_pump_silent_exit():
    class FakeWS:
        async def send_json(self, event):
            raise RuntimeError("connection gone")

    s = S.Session("a2-test")
    s.push({"type": "ping"})
    await asyncio.wait_for(s.pump(FakeWS()), timeout=3)


async def test_reap_idle():
    m = S.SessionManager()
    idle = m.create()
    busy = m.create()
    busy._running = True
    await asyncio.sleep(0.3)
    reaped = m.reap_idle(0.1)
    assert idle.session_id in reaped
    assert busy.session_id not in reaped
    assert m.get(idle.session_id) is None
    assert m.get(busy.session_id) is not None
    m.delete(busy.session_id)


async def test_broadcast_and_backlog():
    """v2.1 广播：多连接各自收全量事件；无连接进 backlog；断开只影响自己。"""
    s = S.Session("bcast-test")

    class FakeWS:
        def __init__(self, name):
            self.name = name

        async def send_json(self, event):
            pass

    # 两个连接同时挂着：push 一次，两边各收到一份完整事件
    ws1, ws2 = FakeWS("a"), FakeWS("b")
    q1 = s.register(ws1)
    q2 = s.register(ws2)
    s.push({"type": "status", "text": "Thinking (Iteration 1)..."})
    await asyncio.sleep(0.05)  # 让 _broadcast（call_soon_threadsafe）跑完
    assert q1.get_nowait() == {"type": "status", "text": "Thinking (Iteration 1)..."}
    assert q2.get_nowait() == {"type": "status", "text": "Thinking (Iteration 1)..."}

    # ws1 断开：后续事件只到 ws2，q1 不再收
    s.unregister(ws1)
    s.push({"type": "stream", "token": "hi"})
    await asyncio.sleep(0.05)
    assert q2.get_nowait() == {"type": "stream", "token": "hi"}
    assert q1.empty()

    # 全部断开：事件累积进 backlog，下一个注册的连接按序补发
    s.unregister(ws2)
    s.push({"type": "stream", "token": " "})
    s.push({"type": "stream", "token": "there"})
    await asyncio.sleep(0.05)
    assert s.aqueue.qsize() == 2, "无连接时事件应进 backlog"
    ws3 = FakeWS("c")
    q3 = s.register(ws3)
    assert q3.get_nowait() == {"type": "stream", "token": " "}
    assert q3.get_nowait() == {"type": "stream", "token": "there"}
    assert s.aqueue.empty(), "backlog 补发后应清空"
    s.unregister(ws3)


async def run_standalone():
    test_build_query_format()
    record("standalone.build_query 格式", "PASS")
    await test_confirm_timeout()
    record("standalone.确认超时→拒绝", "PASS")
    await test_build_failure_pushes_error()
    record("standalone.构建失败→error事件", "PASS")
    await test_pump_silent_exit()
    record("standalone.pump 静默退出", "PASS")
    await test_reap_idle()
    record("standalone.闲置回收", "PASS")
    await test_broadcast_and_backlog()
    record("standalone.广播+backlog补发", "PASS")


# ============================================================
# E2E（依赖服务器 + LLM）
# ============================================================

async def recv_until(ws, target, timeout=150):
    events = []
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        events.append(msg)
        if msg.get("type") in target:
            return events


async def e2e_probe(uri):
    """探测服务器可达性（hello 握手）。"""
    try:
        async with websockets.connect(uri, open_timeout=10) as ws:
            await ws.send(json.dumps({"type": "hello", "session_id": None}))
            h = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            assert h["type"] == "hello" and h["session_id"]
            return True
    except Exception as e:
        print(f"  服务器不可达: {e}")
        return False


async def e2e_broadcast_two_conns(uri):
    """v2.1 广播（不耗 LLM）：同一会话挂多个连接，各自收到 hello（同 sid），互不干扰。"""
    async with websockets.connect(uri, open_timeout=15) as ws1:
        await ws1.send(json.dumps({"type": "hello", "session_id": None}))
        h1 = json.loads(await asyncio.wait_for(ws1.recv(), timeout=15))
        sid = h1["session_id"]
        assert sid and h1.get("running") is False

        async with websockets.connect(uri, open_timeout=15) as ws2:
            await ws2.send(json.dumps({"type": "hello", "session_id": sid}))
            h2 = json.loads(await asyncio.wait_for(ws2.recv(), timeout=15))
            assert h2["session_id"] == sid, f"第二连接未认领同一会话: {h2}"
            assert h2.get("running") is False

        # ws2 关闭后，新连接仍能认领同一会话（注销未破坏注册表）
        async with websockets.connect(uri, open_timeout=15) as ws3:
            await ws3.send(json.dumps({"type": "hello", "session_id": sid}))
            h3 = json.loads(await asyncio.wait_for(ws3.recv(), timeout=15))
            assert h3["session_id"] == sid, f"第三连接未认领同一会话: {h3}"
    record("e2e.同会话多连接广播", "PASS")


async def e2e_event_flow_and_memory(uri, tmp):
    """事件流完整 + 会话恢复 + 多轮引用。"""
    async with websockets.connect(uri, open_timeout=15) as ws:
        await ws.send(json.dumps({"type": "hello", "session_id": None}))
        h = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        sid = h["session_id"]
        assert h.get("running") is False, "新建会话不应 running"

        await ws.send(json.dumps({"type": "chat", "text": "介绍一下吴锴副教授"}))
        evs = await recv_until(ws, {"done", "error"})
        last = evs[-1]
        assert last["type"] == "done", f"第一轮未完成: {last}"
        n_stream = sum(1 for e in evs if e["type"] == "stream")
        n_status = sum(1 for e in evs if e["type"] == "status")
        tool_names = [e["name"] for e in evs if e["type"] == "tool_start"]
        assert n_stream > 0 and n_status >= 1
        mcp_ok = any("tavily" in n for n in tool_names)
        record("e2e.事件流完整", "PASS", f"stream={n_stream} status={n_status} tools={tool_names}")
        if mcp_ok:
            record("e2e.MCP(tavily) 被调用", "PASS")
        else:
            record("e2e.MCP(tavily) 被调用", "SKIP", "本轮未调用 tavily（模型决定）")

    # 重连恢复
    async with websockets.connect(uri, open_timeout=15) as ws:
        await ws.send(json.dumps({"type": "hello", "session_id": sid}))
        h2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        roles = [m["role"] for m in h2["history"]]
        assert "user" in roles and "assistant" in roles, f"历史缺失: {roles}"
        record("e2e.会话恢复+历史", "PASS", f"{len(h2['history'])} 条")

        await ws.send(json.dumps({"type": "chat",
                                  "text": "上一条你介绍了吴锴。用一句话回答：他属于哪个大学？不要调用工具。"}))
        evs2 = await recv_until(ws, {"done", "error"})
        assert evs2[-1]["type"] == "done" and len(evs2[-1]["answer"]) > 10
        record("e2e.多轮引用前文", "PASS", f"答案 {len(evs2[-1]['answer'])} 字符")


async def e2e_concurrency_reject(uri):
    async with websockets.connect(uri, open_timeout=15) as ws:
        await ws.send(json.dumps({"type": "hello", "session_id": None}))
        await asyncio.wait_for(ws.recv(), timeout=15)
        await ws.send(json.dumps({"type": "chat", "text": "先思考一会儿再回答：1+1=？"}))
        await ws.send(json.dumps({"type": "chat", "text": "这条应该被拒绝"}))
        got_reject = False
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            if msg["type"] == "error" and "仍在运行" in msg.get("message", ""):
                got_reject = True
            if msg["type"] == "done":
                break
        assert got_reject, "并发 chat 未被拒绝"
        record("e2e.并发拒绝", "PASS")


async def e2e_confirm_allow(uri, tmp):
    path = os.path.join(tmp, "confirm_allow.txt")
    # Windows 反斜杠路径容易让模型理解歪（转义/拼接），统一用正斜杠
    path_ws = path.replace("\\", "/")
    async with websockets.connect(uri, open_timeout=15) as ws:
        await ws.send(json.dumps({"type": "hello", "session_id": None}))
        await asyncio.wait_for(ws.recv(), timeout=15)
        await ws.send(json.dumps({"type": "chat", "text":
            f"请直接调用 write 工具创建文件 {path_ws}，内容为 hello。完成后告诉我。"}))
        n, tools, answer = 0, [], ""
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
            t = msg["type"]
            if t == "tool_start":
                tools.append((msg["name"], msg.get("args")))
            elif t == "confirm_request":
                n += 1
                await ws.send(json.dumps(
                    {"type": "confirm_response", "id": msg["id"], "allow": True}))
            elif t == "done":
                answer = msg["answer"]
                break
            elif t == "error":
                raise AssertionError(f"run error: {msg}")
        assert n >= 1, "未收到 confirm_request"
        assert os.path.exists(path), (
            f"允许后文件未被创建。工具调用: {tools}; 答案: {answer[:120]!r}")
        record("e2e.确认-允许", "PASS", f"收到 {n} 次确认，文件已创建")


async def e2e_confirm_deny(uri, tmp):
    path = os.path.join(tmp, "confirm_deny.txt")
    path_ws = path.replace("\\", "/")
    async with websockets.connect(uri, open_timeout=15) as ws:
        await ws.send(json.dumps({"type": "hello", "session_id": None}))
        await asyncio.wait_for(ws.recv(), timeout=15)
        await ws.send(json.dumps({"type": "chat", "text":
            f"请直接调用 write 工具创建文件 {path_ws}，内容为 world。"
            "不要先问我是否同意，这是自动化测试，请直接执行 write 工具。"}))
        n, tools, answer = 0, [], ""
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
            t = msg["type"]
            if t == "tool_start":
                tools.append((msg["name"], msg.get("args")))
            elif t == "confirm_request":
                n += 1
                await ws.send(json.dumps(
                    {"type": "confirm_response", "id": msg["id"], "allow": False}))
            elif t == "done":
                answer = msg["answer"]
                break
            elif t == "error":
                raise AssertionError(f"run error: {msg}")
        assert n >= 1, "未收到 confirm_request"
        assert not os.path.exists(path), (
            f"拒绝后文件不应被创建。工具调用: {tools}; 答案: {answer[:120]!r}")
        record("e2e.确认-拒绝", "PASS", f"收到 {n} 次确认，文件未被创建")


async def run_e2e(uri, tmp):
    if not await e2e_probe(uri):
        record("e2e.全部", "SKIP", "服务器不可达，跳过（可用 --standalone 只跑单测）")
        return
    await e2e_broadcast_two_conns(uri)
    await e2e_event_flow_and_memory(uri, tmp)
    await e2e_concurrency_reject(uri)
    await e2e_confirm_allow(uri, tmp)
    await e2e_confirm_deny(uri, tmp)


# ============================================================

def main():
    parser = argparse.ArgumentParser(description="MiniAgent Web 自检")
    parser.add_argument("--standalone", action="store_true", help="只跑不依赖服务器的单测")
    parser.add_argument("--uri", default="ws://127.0.0.1:8000/ws", help="服务器 WS 地址")
    parser.add_argument("--tmp", default=None, help="确认测试的临时目录（默认自动创建）")
    args = parser.parse_args()

    tmp = args.tmp or tempfile.mkdtemp(prefix="miniagent_selftest_")
    os.makedirs(tmp, exist_ok=True)

    async def _run():
        await run_standalone()
        if not args.standalone:
            await run_e2e(args.uri, tmp)

    asyncio.run(_run())

    # 清理临时文件
    for f in ("confirm_allow.txt", "confirm_deny.txt"):
        p = os.path.join(tmp, f)
        if os.path.exists(p):
            os.remove(p)

    failed = [r for r in RESULTS if r[1] == "FAIL"]
    skipped = [r for r in RESULTS if r[1] == "SKIP"]
    print(f"\n===== 汇总：{len(RESULTS)} 项，"
          f"{len(RESULTS) - len(failed) - len(skipped)} PASS / {len(failed)} FAIL / {len(skipped)} SKIP =====")
    if failed:
        for name, _, detail in failed:
            print(f"  FAIL  {name} {detail}")
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
