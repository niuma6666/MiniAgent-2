"""MiniAgent 会话层：Session（历史/并发闸/事件队列）+ SessionManager（内存注册表）。

P1 第一步的产物：Session 从"一次连接 = 一次对话"升级为"一个持久会话"。
- Session 跨 WS 连接存活，持有 agent 实例（首次 chat 构建后复用）与对话历史；
- 事件队列属于会话而非连接：断线期间 agent 产生的事件累积在队列里，重连后补发；
- 内存版注册表：服务器重启即清空（决策：内存版）。
"""

import asyncio
import json
import os
import threading
import time
import uuid
from typing import Dict, List, Optional

from fastapi import WebSocket

from miniagent.agent import MiniAgent
from miniagent.config import load_config
from miniagent.extensions.mcp_client import load_mcp_tools
from miniagent.logger import get_logger

logger = get_logger(__name__)

# mcp.json 固定位于项目根目录（MiniAgent/mcp.json），与启动时 cwd 无关
_MCP_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp.json"
)


def load_mcp_clients_for(agent: MiniAgent) -> List:
    """读取 mcp.json，把每个启用服务器的工具注册进 agent，返回 MCP 客户端列表。

    复刻 cli.py 的加载逻辑，但全程 try/except 兜底：Web 是长驻进程，
    单个 MCP 服务器失败只记日志继续跑，绝不能崩掉整个服务。
    调用方负责在会话清理时 stop 返回的客户端（避免残留 npx 子进程）。
    """
    clients: List = []
    try:
        if not os.path.exists(_MCP_CONFIG_PATH):
            logger.info("mcp.json 不存在，跳过 MCP 工具加载")
            return clients
        with open(_MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        for server_name, server_config in config.get("mcpServers", {}).items():
            if server_config.get("disabled", False):
                continue
            cmd = server_config.get("command")
            args_list = server_config.get("args", [])
            full_cmd = f"{cmd} {' '.join(args_list)}" if isinstance(args_list, list) else cmd
            logger.info(f"Loading MCP server '{server_name}': {full_cmd}")
            try:
                tools = load_mcp_tools(full_cmd)
            except Exception as e:
                logger.error(f"MCP server '{server_name}' 加载失败: {e}")
                continue
            for tool in tools:
                if "_mcp_client" in tool:
                    client = tool["_mcp_client"]
                    if client not in clients:
                        clients.append(client)
                try:
                    agent.add_tool(tool)
                except Exception as e:
                    logger.error(f"注册 MCP 工具 {tool.get('name')} 失败: {e}")
            logger.info(f"MCP server '{server_name}': {len(tools)} tools")
    except Exception as e:
        logger.error(f"加载 mcp.json 失败: {e}")
    return clients


def build_agent(confirm_callback=None):
    """构建一个 MiniAgent 实例：内置工具 + mcp.json 的 MCP 工具 + 确认回调。

    返回 (agent, mcp_clients)；mcp_clients 由调用方（Session）负责在清理时 stop。
    confirm_file_writes=None → 走 env CONFIRM_FILE_WRITES（默认开启）；
    confirm_dangerous 取自配置（env CONFIRM_DANGEROUS，默认开启）。
    """
    cfg = load_config()
    agent = MiniAgent(
        model=cfg.llm.model,
        api_key=cfg.llm.api_key,
        base_url=cfg.llm.api_base,
        temperature=cfg.llm.temperature,
        confirm_file_writes=None,          # 默认开：写/改文件需用户确认
        confirm_dangerous=cfg.confirm_dangerous,
        confirm_callback=confirm_callback,
    )
    for name in cfg.default_tools or agent.get_available_tools():
        agent.load_builtin_tool(name)
    mcp_clients = load_mcp_clients_for(agent)
    return agent, mcp_clients


def build_query(history: List[Dict[str, str]], query: str, limit_turns: int = 10) -> str:
    """复刻 cli._format_history 的历史拼接格式。

    agent 的 _current_query_text（字数约束解析）依赖
    "Conversation history (most recent last):" 标记定位当前消息，
    格式必须与 CLI 完全一致，否则多轮对话的字数约束会跨轮串。
    """
    if not history:
        return query
    recent = history[-(limit_turns * 2):]
    lines = ["Conversation history (most recent last):"]
    for m in recent:
        role = m.get("role", "")
        content = (m.get("content", "") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) + "\n\n" + query


class Session:
    """一个持久会话：跨连接存活，持有 agent 实例与对话历史。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.history: List[Dict[str, str]] = []
        self.agent: Optional[MiniAgent] = None
        self.mcp_clients: List = []
        self._running = False
        self._chunks = ""
        self._suppressed = False
        self._t0 = 0.0
        self.last_active = time.monotonic()   # 闲置回收用（A3）
        # 确认桥：cid → {"event": threading.Event, "allow": bool}
        self._pending_confirms: Dict[str, dict] = {}
        self._confirm_lock = threading.Lock()
        # 必须在事件循环线程里创建（WS 处理器中调用，天然满足）
        self.loop = asyncio.get_running_loop()
        self.aqueue: asyncio.Queue = asyncio.Queue()

    # ---------- 事件通道（P0 同款） ----------
    def push(self, event: dict):
        """工作线程里调用，线程安全投递到会话事件队列"""
        self.loop.call_soon_threadsafe(self.aqueue.put_nowait, event)

    async def pump(self, ws: WebSocket):
        """把会话队列里的事件逐条发给当前连接（每连接一个 pump task）。

        A2：发送失败（连接已断开等）时静默退出，不再抛未处理异常；
        连接级清理由 ws_endpoint 的 finally 负责。
        """
        while True:
            event = await self.aqueue.get()
            try:
                await ws.send_json(event)
            except Exception:
                return

    # ---------- MiniAgent 回调适配（P0 同款） ----------
    def tool_cb(self, event, name, payload):
        if event == "start":
            self.push({"type": "tool_start", "name": name,
                       "args": payload.get("arguments", {})})
        elif event == "end":
            self.push({"type": "tool_end", "name": name,
                       "result": payload.get("result"),
                       "elapsed": round(time.perf_counter() - self._t0, 2)})

    def status_cb(self, text):
        self.push({"type": "status", "text": text})

    def reset(self):
        """run_with_tools 每轮 LLM 调用前会自动调用（有 reset 方法时）"""
        self._chunks = ""
        self._suppressed = False

    def __call__(self, token):
        """作为 stream_callback 传入；过滤掉 TOOL:/ARGS: 文本块"""
        self._chunks += token
        if "TOOL:" in self._chunks or "Tool:" in self._chunks or "工具:" in self._chunks:
            self._suppressed = True
            return
        if not self._suppressed:
            self.push({"type": "stream", "token": token})

    # ---------- 确认桥（P1 第二步） ----------
    def confirm_callback(self, desc: str) -> bool:
        """工作线程里被 agent 同步调用：发确认请求并阻塞等待用户决定。

        流程：登记 holder → push confirm_request → event.wait(timeout)
        → 收到 confirm_response（事件循环线程 resolve）或超时 → 返回 allow。
        超时（CONFIRM_TIMEOUT，默认 60s）或会话清理时按"拒绝"处理。
        """
        cid = uuid.uuid4().hex[:12]
        holder = {"event": threading.Event(), "allow": False}
        with self._confirm_lock:
            self._pending_confirms[cid] = holder
        self.push({"type": "confirm_request", "id": cid, "desc": desc})
        try:
            timeout = float(os.environ.get("CONFIRM_TIMEOUT", "60"))
        except ValueError:
            timeout = 60.0
        holder["event"].wait(timeout=timeout)
        with self._confirm_lock:
            self._pending_confirms.pop(cid, None)
            return bool(holder["allow"])

    def resolve_confirmation(self, cid: str, allow: bool) -> bool:
        """事件循环线程调用（WS 收到 confirm_response）：解挂对应确认。

        返回是否找到该确认；找不到说明已超时/已清理，忽略即可。
        """
        with self._confirm_lock:
            holder = self._pending_confirms.get(cid)
            if holder is None:
                return False
            holder["allow"] = bool(allow)
            holder["event"].set()
        return True

    def resolve_all_confirmations(self, allow: bool = False):
        """断开/清理时调用：把所有等待中的确认按给定值（默认拒绝）解挂。

        防止工作线程在用户刷新页面后仍白等 60s。
        """
        with self._confirm_lock:
            holders = list(self._pending_confirms.values())
            self._pending_confirms.clear()
        for h in holders:
            h["allow"] = bool(allow)
            h["event"].set()

    # ---------- 工作线程入口 ----------
    def run_agent(self, query: str):
        """工作线程里执行一轮对话：复用 agent、维护历史、推 done/error。

        历史管道：query 拼上 CLI 同款历史前缀后喂给 agent；
        完成后把本轮 user+assistant 追加进 history 并截断到最近 10 轮。
        """
        self._running = True
        self.last_active = time.monotonic()
        try:
            if self.agent is None:
                # A1：构建失败（缺 key、MCP 加载崩等）不能逃逸出工作线程，
                # 必须推 error 事件并复位 _running，前端才能看到失败而非挂起。
                try:
                    self.agent, self.mcp_clients = build_agent(
                        confirm_callback=self.confirm_callback)
                except Exception as e:
                    logger.error(f"构建 agent 失败: {e}")
                    self.push({"type": "error",
                               "message": f"初始化失败：{type(e).__name__}: {e}"})
                    return
            self._chunks = ""
            self._suppressed = False
            full_query = build_query(self.history, query)
            self._t0 = time.perf_counter()
            try:
                answer = self.agent.run_pipeline(
                    full_query,
                    tool_callback=self.tool_cb,
                    status_callback=self.status_cb,
                    stream_callback=self,
                    mode="text",
                )
            except Exception as e:
                self.push({"type": "error", "message": f"{type(e).__name__}: {e}"})
                return
            self.history.append({"role": "user", "content": query})
            self.history.append({"role": "assistant", "content": answer})
            # 截断防膨胀：最多保留最近 10 轮
            self.history = self.history[-20:]
            self.push({"type": "done", "answer": answer,
                       "elapsed": round(time.perf_counter() - self._t0, 2)})
        finally:
            self._running = False
            self.last_active = time.monotonic()

    def cleanup(self):
        """解挂所有等待中的确认（按拒绝），再停止 MCP 子进程。

        在会话删除或服务器关闭时调用；终止 npx 子进程并 join 其读取线程，
        避免残留进程与退出时的输出线程崩溃。
        """
        self.resolve_all_confirmations(False)
        for client in self.mcp_clients:
            try:
                client.stop()
            except Exception as e:
                logger.warning(f"停止 MCP 客户端失败: {e}")
        self.mcp_clients = []
        if self.agent is not None and hasattr(self.agent, "cleanup"):
            try:
                self.agent.cleanup()
            except Exception:
                pass


class SessionManager:
    """内存版会话注册表（服务器重启即清空）。"""

    def __init__(self):
        self._sessions: Dict[str, Session] = {}

    def create(self) -> Session:
        sid = uuid.uuid4().hex
        s = Session(sid)
        self._sessions[sid] = s
        return s

    def get(self, sid: str) -> Optional[Session]:
        return self._sessions.get(sid)

    def delete(self, sid: str) -> None:
        s = self._sessions.pop(sid, None)
        if s:
            s.cleanup()

    def list(self) -> List[str]:
        return list(self._sessions.keys())

    def reap_idle(self, timeout: float) -> List[str]:
        """回收超过 timeout 秒无活动的会话（A3：闲置回收）。

        正在运行（_running）的会话不回收。返回被回收的会话 id 列表。
        """
        now = time.monotonic()
        deadline = now - timeout
        stale = [
            sid for sid, s in self._sessions.items()
            if s.last_active < deadline and not s._running
        ]
        for sid in stale:
            self.delete(sid)
        return stale
