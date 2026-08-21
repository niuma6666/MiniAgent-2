"""MiniAgent Web 桥接 — P0.5: FastAPI + WebSocket 事件桥（会话化）

会话层（Session/SessionManager）在 server/session.py，本文件只负责路由与握手。
"""
import asyncio
import os
import time

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

from .session import SessionManager

app = FastAPI()
manager = SessionManager()

# hello 时最多回传的历史轮数（每轮 = user + assistant 两条）
MAX_HISTORY_TURNS = 10

# 闲置回收（A3）：扫描间隔与超时（env SESSION_IDLE_TIMEOUT，默认 1800s）
REAPER_INTERVAL = 30.0
REAPER_IDLE_TIMEOUT = 1800.0


def _idle_timeout() -> float:
    try:
        return float(os.environ.get("SESSION_IDLE_TIMEOUT", str(REAPER_IDLE_TIMEOUT)))
    except ValueError:
        return REAPER_IDLE_TIMEOUT


async def _idle_reaper_loop():
    """后台任务：定期回收超过 SESSION_IDLE_TIMEOUT 无活动的会话。"""
    while True:
        await asyncio.sleep(REAPER_INTERVAL)
        try:
            stale = manager.reap_idle(_idle_timeout())
            if stale:
                print(f"[reaper] 回收闲置会话: {stale}")
        except Exception as e:
            print(f"[reaper] 扫描失败: {e}")


@app.on_event("startup")
async def _start_reaper():
    asyncio.create_task(_idle_reaper_loop())


@app.on_event("shutdown")
async def _shutdown_cleanup():
    """服务器关闭时停止所有会话的 MCP 子进程，避免残留 npx 进程。"""
    for sid in manager.list():
        session = manager.get(sid)
        if session:
            try:
                session.cleanup()
            except Exception as e:
                print(f"[shutdown] cleanup {sid} failed: {e}")


def _hello_payload(session):
    return {
        "type": "hello",
        "session_id": session.session_id,
        "history": session.history[-(MAX_HISTORY_TURNS * 2):],
        "running": session._running,   # B2：运行中刷新重连时前端据此禁用输入
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    session = None
    greeted = False
    pump_task = None
    try:
        while True:
            data = await ws.receive_json()

            # ---- 首帧握手：hello 认领/创建会话 ----
            if not greeted:
                if data.get("type") == "hello":
                    sid = data.get("session_id")
                    session = manager.get(sid) if sid else None
                    if session is None:
                        session = manager.create()
                else:
                    # 首帧不是 hello（如直接 chat）：兜底新建会话
                    session = manager.create()
                greeted = True
                session.last_active = time.monotonic()
                pump_task = asyncio.create_task(session.pump(ws))
                await ws.send_json(_hello_payload(session))

                if data.get("type") != "hello":
                    # 把被当作握手消费掉的 chat 首帧补执行
                    if not session._running:
                        session._running = True
                        asyncio.create_task(
                            asyncio.to_thread(session.run_agent, data.get("text", "")))
                continue

            # ---- 常规消息 ----
            if session:
                session.last_active = time.monotonic()   # 连接活跃即视为会话活跃（A3）
            if data.get("type") == "chat":
                if session._running:
                    await ws.send_json({"type": "error",
                                        "message": "上一条请求仍在运行，请稍候"})
                    continue
                session._running = True
                asyncio.create_task(
                    asyncio.to_thread(session.run_agent, data.get("text", "")))
            elif data.get("type") == "confirm_response":
                # 确认桥：回应 agent 等待中的确认请求
                session.resolve_confirmation(
                    data.get("id", ""), bool(data.get("allow", False)))
    except WebSocketDisconnect:
        pass
    finally:
        # 只取消本连接的 pump；Session 跨连接存活，不销毁
        if pump_task:
            pump_task.cancel()
        # 断开即解挂本会话所有等待中的确认（按拒绝），
        # 防止工作线程在用户刷新后仍白等 CONFIRM_TIMEOUT。
        if session:
            session.resolve_all_confirmations(False)


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>MiniAgent Web</title>
<!-- 修复3：marked 渲染 markdown（bootcdn 主源，国内可达；jsdelivr 兜底） -->
<script src="https://cdn.bootcdn.net/ajax/libs/marked/4.3.0/marked.min.js"></script>
<script>
  if (typeof marked === 'undefined') {
    document.write('<script src="https://cdn.jsdelivr.net/npm/marked@4.3.0/marked.min.js"><\\/script>');
  }
</script>
<style>
  body { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; margin: 20px; max-width: 900px; }
  #events { font-size: 14px; line-height: 1.6; }
  .status { color: #999; font-size: 12px; margin: 4px 0; }
  .tool   { color: #07c; font-family: Consolas, monospace; font-size: 12px; margin: 4px 0; }
  .answer { color: #080; }
  .error  { color: #c00; }
  .user   { color: #606; font-weight: 600; margin-top: 12px; }
  /* 修复1：流式回答是单个连续块 */
  #stream { margin: 6px 0; }
  /* markdown 基础排版（修复3） */
  .md h1, .md h2, .md h3, .md h4 { margin: 10px 0 4px; }
  .md p { margin: 4px 0; }
  .md code { background: #f0f0f0; padding: 1px 5px; border-radius: 3px; font-family: Consolas, monospace; }
  .md pre { background: #f6f8fa; padding: 10px; border-radius: 5px; overflow-x: auto; }
  .md pre code { background: none; padding: 0; }
  .md ul, .md ol { margin: 4px 0 4px 22px; padding: 0; }
  .md blockquote { border-left: 3px solid #ccc; margin: 4px 0; padding-left: 10px; color: #666; }
  .md table { border-collapse: collapse; }
  .md th, .md td { border: 1px solid #ddd; padding: 4px 8px; }
  /* P1 第二步：确认弹窗 */
  #confirm-overlay {
    display: none;
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.35);
    align-items: center; justify-content: center;
    z-index: 100;
  }
  #confirm-overlay.show { display: flex; }
  #confirm-box {
    background: #fff; border-radius: 8px; padding: 16px 20px;
    max-width: 520px; box-shadow: 0 4px 16px rgba(0,0,0,0.25);
    font-size: 14px;
  }
  #confirm-box .c-title { font-weight: 600; margin-bottom: 8px; }
  #confirm-desc { color: #444; word-break: break-all; margin-bottom: 14px; font-family: Consolas, monospace; font-size: 13px; }
  #confirm-box button {
    margin-right: 8px; padding: 6px 18px; border: none; border-radius: 5px;
    cursor: pointer; font-size: 14px;
  }
  #confirm-allow { background: #2e7d32; color: #fff; }
  #confirm-deny  { background: #d32f2f; color: #fff; }
</style>
</head>
<body>
<h3>MiniAgent — P0 事件桥测试</h3>
<input id="input" size="60" placeholder="输入指令...">
<button id="sendBtn" onclick="send()">发送</button>
<button onclick="newSession()">新会话</button>
<div id="events"></div>
<div id="confirm-overlay">
  <div id="confirm-box">
    <div class="c-title">⚠️ Agent 请求确认</div>
    <div id="confirm-desc"></div>
    <button id="confirm-allow" onclick="confirmAnswer(true)">允许</button>
    <button id="confirm-deny" onclick="confirmAnswer(false)">拒绝</button>
  </div>
</div>
<script>
  const box = document.getElementById('events');
  let streamBuf = '';
  let answerEl = null;   // 当前答案容器（动态建在对话末尾）
  let sessionId = localStorage.getItem('miniagent_sid') || null;
  let pendingConfirmId = null;   // 待回应的确认请求 id

  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    ws.send(JSON.stringify({type: 'hello', session_id: sessionId}));
  };

  // markdown 渲染；marked 加载失败时退回纯文本（转义防 XSS）
  function render(md) {
    const parse = window.marked && (window.marked.parse || window.marked);
    if (parse) {
      try { return parse(md, { breaks: true }); } catch (e) { /* fall through */ }
    }
    return '<pre style="white-space:pre-wrap">'
      + md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      + '</pre>';
  }

  function scroll() { box.scrollTop = box.scrollHeight; }

  function append(text, cls) {
    const div = document.createElement('div');
    div.className = cls;
    div.textContent = text;
    box.appendChild(div);
    scroll();
  }

  // P1 第一步：历史消息渲染（重连恢复的旧轮次，独立块）
  function appendAnswer(md) {
    const div = document.createElement('div');
    div.className = 'md';
    div.innerHTML = render(stripFinalAnswerPrefix(md));
    box.appendChild(div);
    scroll();
  }

  // 修复2b：渲染时剥掉开头的 FINAL_ANSWER: 前缀
  function stripFinalAnswerPrefix(s) {
    return s.replace(/^\\s*FINAL_ANSWER:\\s*/i, '');
  }

  // P0收尾：工具结果显示为可读文本（对象转 JSON），不再出现 [object Object]
  function formatToolResult(result) {
    let s;
    try { s = (typeof result === 'string') ? result : JSON.stringify(result); }
    catch (e) { s = String(result); }
    return s.length > 200 ? s.slice(0, 200) + '…' : s;
  }

  // P0收尾：答案容器建在对话末尾；appendChild 对已存在元素是"移动"，
  // 每次渲染都把容器挪到列表末尾 → 答案永远出现在提问/工具行之后。
  function ensureAnswerEl() {
    if (!answerEl) {
      answerEl = document.createElement('div');
      answerEl.className = 'md';
      box.appendChild(answerEl);
    }
    return answerEl;
  }

  // 修复1：流式 token 累积进当前答案容器，整段连续显示
  function onStream(token) {
    streamBuf += token;
    ensureAnswerEl().innerHTML = render(stripFinalAnswerPrefix(streamBuf));
    box.appendChild(answerEl);
    scroll();
  }

  // 修复2b：每轮开始（status 事件）开新段，清掉上一轮泄漏的 TOOL 碎片
  function onStatus(text) {
    streamBuf = '';
    if (answerEl) answerEl.innerHTML = '';
    append('… ' + text, 'status');
    scroll();
  }

  // 修复2a：done 到达 → 用完整答案替换当前答案容器，不再追加新块
  function onDone(answer) {
    streamBuf = '';
    ensureAnswerEl().innerHTML = render(stripFinalAnswerPrefix(answer));
    box.appendChild(answerEl);
    scroll();
  }

  function newRound() {
    streamBuf = '';
    answerEl = null;   // 下一轮从新容器开始
  }

  // P1 第二步：确认弹窗
  function showConfirm(desc) {
    document.getElementById('confirm-desc').textContent = desc;
    document.getElementById('confirm-overlay').classList.add('show');
  }
  function confirmAnswer(allow) {
    if (pendingConfirmId) {
      ws.send(JSON.stringify({type: 'confirm_response', id: pendingConfirmId, allow}));
      pendingConfirmId = null;
    }
    document.getElementById('confirm-overlay').classList.remove('show');
  }

  // B2：运行中禁用发送（hello 带 running 状态 + done/error 恢复）
  function setRunningUI(running) {
    document.getElementById('sendBtn').disabled = running;
    document.getElementById('input').disabled = running;
    document.getElementById('sendBtn').textContent = running ? '运行中…' : '发送';
  }

  // B3：新建会话（清本地会话 id 后重连）
  function newSession() {
    localStorage.removeItem('miniagent_sid');
    location.reload();
  }

  ws.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (e.type === 'hello') {
      localStorage.setItem('miniagent_sid', e.session_id);
      if (e.history && e.history.length) {
        for (const msg of e.history) {
          if (msg.role === 'user')        append('you: ' + msg.content, 'user');
          else if (msg.role === 'assistant') appendAnswer(msg.content);
        }
      }
      // 运行中刷新页面重连：恢复"运行中"状态，done 到达时自动恢复
      setRunningUI(e.running === true);
      return;
    }
    if (e.type === 'stream')        onStream(e.token);
    else if (e.type === 'status')   onStatus(e.text);
    else if (e.type === 'tool_start') append('🔧 ' + e.name + ' ' + JSON.stringify(e.args), 'tool');
    else if (e.type === 'tool_end')   append('→ ' + formatToolResult(e.result), 'tool');
    else if (e.type === 'confirm_request') {
      pendingConfirmId = e.id;
      showConfirm(e.desc);
    }
    else if (e.type === 'done')       { onDone(e.answer); setRunningUI(false); }
    else if (e.type === 'error')      { append('❌ ' + e.message, 'error'); setRunningUI(false); }
  };

  function send() {
    const t = document.getElementById('input').value;
    if (!t) return;
    document.getElementById('input').value = '';
    newRound();
    append('you: ' + t, 'user');
    ws.send(JSON.stringify({type: 'chat', text: t}));
    setRunningUI(true);   // 发送后立即禁用，直到 done/error
  }
  document.getElementById('input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') send();
  });
</script>
</body>
</html>
"""


# ---- P2：React 前端静态托管（server/web/dist）----
# 构建产物存在时由 FastAPI 直接托管（生产模式），否则回退到内联 P0 页面。
# dev 模式请用 vite：server/web 下 `npm run dev`（5173 端口，/ws 代理到本服务）。
WEB_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "dist")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_file = os.path.join(WEB_DIST, "index.html")
    if os.path.isfile(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return INDEX_HTML


@app.get("/assets/{path:path}")
async def web_asset(path: str):
    """托管 Vite 构建产物（assets/ 下的 js/css 等）。带目录穿越防护。"""
    base = os.path.realpath(os.path.join(WEB_DIST, "assets"))
    target = os.path.realpath(os.path.join(base, path))
    if not target.startswith(base + os.sep) or not os.path.isfile(target):
        raise HTTPException(status_code=404)
    return FileResponse(target)