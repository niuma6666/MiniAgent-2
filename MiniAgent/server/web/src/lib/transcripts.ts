/**
 * 会话转录本地缓存（P3.1）。
 *
 * 背景：服务端会话注册表是内存版（重启 / 闲置回收即清空），hello 认领失败时
 * 服务端会静默新建会话 —— 前端无从分辨「恢复成功」还是「会话已死」。
 * 这里把每个会话的对话转录（user/assistant 文本）缓存进 localStorage：
 * - 认领成功 → 用服务端返回的 history 覆盖缓存；
 * - 每轮 done → 从 items 派生最新转录写回；
 * - 认领失败（返回了新 session_id）→ 读缓存展示旧对话（附提示条），
 *   并把缓存挂到新会话名下，刷新后依然可见。
 *
 * 体积控制：单条消息截断、单会话最多 40 条、全局最多 30 个会话、
 * 总量超 1.5MB 时按最旧优先丢弃。
 */

export interface TranscriptMsg {
  role: 'user' | 'assistant'
  content: string
}

interface Entry {
  ts: number
  msgs: TranscriptMsg[]
}

const KEY = 'miniagent_transcripts_v1'
const MAX_SESSIONS = 30
const MAX_MSGS = 40
const MAX_MSG_CHARS = 8000
const MAX_TOTAL_BYTES = 1.5 * 1024 * 1024

function loadAll(): Record<string, Entry> {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return {}
    const d = JSON.parse(raw)
    return d && typeof d === 'object' && !Array.isArray(d) ? d : {}
  } catch {
    return {}
  }
}

function persistAll(all: Record<string, Entry>) {
  try {
    let entries = Object.entries(all)
    let payload = JSON.stringify(all)
    // 体积兜底：从最旧开始丢，直到进入预算（至少保留 1 个）
    while (payload.length > MAX_TOTAL_BYTES && entries.length > 1) {
      entries.sort((a, b) => a[1].ts - b[1].ts)
      entries.shift()
      payload = JSON.stringify(Object.fromEntries(entries))
    }
    localStorage.setItem(KEY, payload)
  } catch {
    /* 超限/异常静默降级 */
  }
}

/** 读某个会话的本地转录；无缓存返回 null。 */
export function loadTranscript(sid: string): TranscriptMsg[] | null {
  if (!sid) return null
  const e = loadAll()[sid]
  if (!e || !Array.isArray(e.msgs) || e.msgs.length === 0) return null
  return e.msgs
}

/** 删除某个会话的本地转录（配合侧栏「删除会话」）。 */
export function deleteTranscript(sid: string) {
  if (!sid) return
  const all = loadAll()
  if (!(sid in all)) return
  delete all[sid]
  persistAll(all)
}

/** 写某个会话的本地转录（截断 + 数量/体积裁剪）。 */
export function saveTranscript(sid: string, msgs: TranscriptMsg[]) {
  if (!sid || !Array.isArray(msgs) || msgs.length === 0) return
  const all = loadAll()
  all[sid] = {
    ts: Date.now(),
    msgs: msgs
      .filter((m) => m && typeof m.content === 'string')
      .slice(-MAX_MSGS)
      .map((m) => ({
        role: m.role === 'assistant' ? 'assistant' : 'user',
        content: m.content.slice(0, MAX_MSG_CHARS),
      })),
  }
  const entries = Object.entries(all)
  if (entries.length > MAX_SESSIONS) {
    entries.sort((a, b) => b[1].ts - a[1].ts)
    persistAll(Object.fromEntries(entries.slice(0, MAX_SESSIONS)))
  } else {
    persistAll(all)
  }
}
