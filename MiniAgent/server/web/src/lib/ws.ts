import { useAgentStore } from '../store'

/**
 * WebSocket 事件桥客户端（协议 v2，见 server/PROTOCOL.md）。
 *
 * - 模块级单例 socket：无论多少组件调用 connect() 都只建一条连接；
 * - 自动重连（2s 退避，页面关闭/主动 disconnect 除外）；
 * - session_id 存 localStorage（与 P0 内联页同键名，可无缝接续旧会话）；
 * - 事件处理全部委托给 store.applyEvent（单一数据源）。
 */

const RECONNECT_DELAY = 2000

let socket: WebSocket | null = null
let retryTimer: number | null = null
let closedByUs = false

export function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return
  }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${proto}://${location.host}/ws`)
  closedByUs = false

  socket.onopen = () => {
    const { sessionId } = useAgentStore.getState()
    socket!.send(JSON.stringify({ type: 'hello', session_id: sessionId }))
  }

  socket.onmessage = (ev) => {
    let e: any
    try {
      e = JSON.parse(ev.data)
    } catch {
      return
    }
    useAgentStore.getState().applyEvent(e)
  }

  socket.onclose = () => {
    useAgentStore.setState({ connected: false })
    socket = null
    if (!closedByUs) {
      retryTimer = window.setTimeout(connect, RECONNECT_DELAY)
    }
  }

  socket.onerror = () => {
    /* onclose 随后触发，统一在那里处理重连 */
  }
}

/** 发送一条客户端 → 服务器事件（未连接时静默丢弃）。 */
export function send(obj: unknown) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(obj))
  }
}

export function disconnect() {
  closedByUs = true
  if (retryTimer) {
    window.clearTimeout(retryTimer)
    retryTimer = null
  }
  socket?.close()
  socket = null
  useAgentStore.setState({ connected: false })
}

/** 新建会话：清本地 session id 后整页重载（服务端 hello 时建新会话）。 */
export function newSession() {
  localStorage.removeItem('miniagent_sid')
  location.reload()
}
