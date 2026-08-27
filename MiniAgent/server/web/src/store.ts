import { create } from 'zustand'
import { upsertSession, listSessions, migrateSession } from './lib/sessions'
import { loadTranscript, saveTranscript, type TranscriptMsg } from './lib/transcripts'

/**
 * Agent 会话状态（P2.2）。
 *
 * 设计：单一事件源 = items 列表（聊天流），工具日志面板与状态条都从这里派生，
 * 避免多份状态同步不一致。WS 事件经 ws.ts 统一投递到 applyEvent。
 */

export type ChatItemKind = 'user' | 'status' | 'error' | 'tool' | 'answer' | 'notice'

export interface ChatItem {
  kind: ChatItemKind
  uid: number
  text: string // user/status/error/answer 文本；tool 的 args 展示文本
  name?: string // tool
  args?: unknown
  result?: unknown
  elapsed?: number
  done?: boolean // tool 完成 / answer 定稿
}

export interface ConfirmState {
  id: string | null
  desc: string
}

export interface AgentState {
  connected: boolean
  sessionId: string | null
  running: boolean
  items: ChatItem[]
  lastStatus: string
  lastAnswerElapsed: number | null
  pendingConfirm: ConfirmState

  /** WS 事件分派（ws.ts 调用） */
  applyEvent: (e: Record<string, any>) => void
  /** 用户发送本地回显（乐观更新，服务端事件随后到达） */
  userSent: (text: string) => void
  clearPendingConfirm: () => void
}

const MAX_ITEMS = 600

/**
 * 轻量事件钩子：桌宠等附加 UI 订阅原始 WS 事件流（只读，不改 applyEvent 语义）。
 * applyEvent 每次收到事件时按注册顺序通知；返回取消订阅函数。
 */
const eventListeners = new Set<(e: Record<string, any>) => void>()
export function onAgentEvent(cb: (e: Record<string, any>) => void): () => void {
  eventListeners.add(cb)
  return () => {
    eventListeners.delete(cb)
  }
}

let uidSeq = 0
let currentAnswerUid: number | null = null

function nextUid() {
  return ++uidSeq
}

function pushItem(items: ChatItem[], item: ChatItem): ChatItem[] {
  const next = [...items, item]
  return next.length > MAX_ITEMS ? next.slice(-MAX_ITEMS) : next
}

function findToolIndex(items: ChatItem[], name: string): number {
  // 找最后一个同名且未结束的 tool 项（tool_end 不携带 id，靠 name+顺序配对）
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i]
    if (it.kind === 'tool' && it.name === name && !it.done) return i
  }
  return -1
}

function stripFinalAnswerPrefix(s: string): string {
  return s.replace(/^\s*FINAL_ANSWER:\s*/i, '')
}

const initialItems: ChatItem[] = []

/** 启动时恢复上次（或侧栏指定）的 session_id —— ws.ts hello 据此向服务端认领会话 */
function initialSessionId(): string | null {
  try {
    return localStorage.getItem('miniagent_sid')
  } catch {
    return null
  }
}

export const useAgentStore = create<AgentState>((set, get) => ({
  connected: false,
  sessionId: initialSessionId(),
  running: false,
  items: initialItems,
  lastStatus: '',
  lastAnswerElapsed: null,
  pendingConfirm: { id: null, desc: '' },

  applyEvent(e) {
    for (const cb of eventListeners) cb(e)
    const s = get()
    switch (e.type) {
      case 'hello': {
        // hello 到达时 store 里的 sessionId 仍是「请求认领的 sid」：
        // 与返回值不一致 = 服务端不认识该会话（重启/闲置回收已清空）。
        const requestedSid = s.sessionId
        const claimed = !!requestedSid && e.session_id === requestedSid

        const items: ChatItem[] = []
        let cached: TranscriptMsg[] | null = null
        if (!claimed && requestedSid) {
          // 认领失败：展示本地缓存的旧对话（若有），并把缓存挂到新会话名下
          cached = loadTranscript(requestedSid)
          items.push({
            kind: 'notice',
            uid: nextUid(),
            text: cached
              ? '服务端会话已失效（服务器重启或超时回收），以下为本地缓存记录；发送新消息将接续到新会话。'
              : '服务端会话已失效，已开启新会话。',
          })
          if (cached) saveTranscript(e.session_id, cached)
          // 旧条目原位顶替为新 sid（标题/时间戳继承）→ 侧栏顺序不变；
          // 后面 upsertSession(..., false) 会发现条目已存在，仅保底登记
          migrateSession(requestedSid, e.session_id)
        } else if ((e.history ?? []).length > 0) {
          // 认领成功：用服务端历史覆盖本地缓存
          saveTranscript(e.session_id, e.history)
        } else {
          // 认领成功但服务端历史为空（如缓存挂靠后的刷新）：展示挂靠的缓存
          cached = loadTranscript(e.session_id)
          if (cached) {
            items.push({
              kind: 'notice',
              uid: nextUid(),
              text: '以下为本地缓存记录（服务端历史为空）。',
            })
          }
        }

        if (cached) {
          for (const m of cached) {
            if (m.role === 'user') {
              items.push({ kind: 'user', uid: nextUid(), text: m.content })
            } else {
              items.push({ kind: 'answer', uid: nextUid(), text: m.content, done: true })
            }
          }
        }
        for (const m of e.history ?? []) {
          if (m.role === 'user') {
            items.push({ kind: 'user', uid: nextUid(), text: m.content })
          } else if (m.role === 'assistant') {
            items.push({ kind: 'answer', uid: nextUid(), text: m.content, done: true })
          }
        }
        currentAnswerUid = null
        // 持久化 session_id（刷新/重连可接续）+ 登记到会话注册表（侧栏展示）
        try {
          localStorage.setItem('miniagent_sid', e.session_id)
        } catch {
          /* 静默 */
        }
        upsertSession(e.session_id, undefined, false) // 仅登记，不动排序（避免点击会话被顶到首位）
        set({
          connected: true,
          sessionId: e.session_id,
          running: e.running === true,
          items,
          lastStatus: '',
          lastAnswerElapsed: null,
        })
        break
      }
      case 'stream': {
        let items = s.items
        if (currentAnswerUid === null) {
          const uid = nextUid()
          currentAnswerUid = uid
          items = pushItem(items, { kind: 'answer', uid, text: '' })
        }
        items = items.map((it) =>
          it.uid === currentAnswerUid ? { ...it, text: it.text + e.token } : it,
        )
        set({ items })
        break
      }
      case 'status': {
        // 与 P0 同语义：新一轮 iteration 开始 → 清空当前答案容器 + 记一行状态
        let items = s.items
        if (currentAnswerUid !== null) {
          items = items.map((it) =>
            it.uid === currentAnswerUid ? { ...it, text: '' } : it,
          )
        }
        items = pushItem(items, { kind: 'status', uid: nextUid(), text: e.text })
        set({ items, lastStatus: e.text })
        break
      }
      case 'tool_start': {
        const argsText = safeStringify(e.args)
        const items = pushItem(s.items, {
          kind: 'tool',
          uid: nextUid(),
          text: argsText,
          name: e.name,
          args: e.args,
        })
        set({ items })
        break
      }
      case 'tool_end': {
        const idx = findToolIndex(s.items, e.name)
        if (idx >= 0) {
          const items = s.items.map((it, i) =>
            i === idx
              ? { ...it, result: e.result, elapsed: e.elapsed, done: true }
              : it,
          )
          set({ items })
        }
        break
      }
      case 'done': {
        let items = s.items
        const answer = String(e.answer ?? '')
        if (currentAnswerUid === null) {
          const uid = nextUid()
          currentAnswerUid = uid
          items = pushItem(items, { kind: 'answer', uid, text: '' })
        }
        items = items.map((it) =>
          it.uid === currentAnswerUid ? { ...it, text: answer, done: true } : it,
        )
        set({
          items,
          running: false,
          lastAnswerElapsed: e.elapsed ?? null,
          lastStatus: '',
        })
        // 本地缓存转录：从 items 派生（user + 已定稿 answer）
        const sid = get().sessionId
        if (sid) saveTranscript(sid, deriveTranscript(items))
        break
      }
      case 'error': {
        const items = pushItem(s.items, { kind: 'error', uid: nextUid(), text: e.message })
        set({ items, running: false })
        break
      }
      case 'confirm_request': {
        set({ pendingConfirm: { id: e.id, desc: e.desc } })
        break
      }
      default:
        break
    }
  },

  userSent(text) {
    const items = pushItem(get().items, { kind: 'user', uid: nextUid(), text })
    currentAnswerUid = null // 新问题 → 下一段答案从新容器开始
    // 会话标题：首个用户消息截断 24 字（已有自定义标题则保留）
    const sid = get().sessionId
    if (sid) {
      const prev = listSessions().find((s) => s.id === sid)
      // 产生了新消息 → touch=true，此时才允许该会话在列表中上浮
      upsertSession(
        sid,
        !prev || prev.title === '新会话' ? text.slice(0, 24) : undefined,
        true,
      )
    }
    set({ items, running: true, lastAnswerElapsed: null })
  },

  clearPendingConfirm() {
    set({ pendingConfirm: { id: null, desc: '' } })
  },
}))

function safeStringify(v: unknown): string {
  if (v === undefined || v === null) return ''
  try {
    return typeof v === 'string' ? v : JSON.stringify(v)
  } catch {
    return String(v)
  }
}

/** 从聊天 items 派生纯转录（user / 已定稿 answer），用于本地缓存 */
function deriveTranscript(items: ChatItem[]): TranscriptMsg[] {
  const out: TranscriptMsg[] = []
  for (const it of items) {
    if (it.kind === 'user') out.push({ role: 'user', content: it.text })
    else if (it.kind === 'answer' && it.done) out.push({ role: 'assistant', content: it.text })
  }
  return out
}

/** 渲染用：剥离开头 FINAL_ANSWER: 前缀（模型可能一稿两写） */
export function stripPrefix(s: string): string {
  return stripFinalAnswerPrefix(s)
}

/** 工具结果显示：对象转 JSON，超长截断 */
export function formatToolResult(result: unknown, max = 200): string {
  const text = safeStringify(result)
  return text.length > max ? text.slice(0, max) + '…' : text
}
