/**
 * 会话注册表（前端侧）：localStorage 记录历史 session_id，
 * 侧栏按日期分组展示；点击切换 = 写 miniagent_sid 后刷新，
 * 服务端 hello 会认领回该会话（见 server/app.py / PROTOCOL.md）。
 */

export interface SessionMeta {
  id: string
  title: string
  updatedAt: number
}

const KEY = 'miniagent_sessions_v1'
const MAX_SESSIONS = 50

export function listSessions(): SessionMeta[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const d = JSON.parse(raw)
    if (!Array.isArray(d.sessions)) return []
    return d.sessions
      .filter((s: unknown): s is SessionMeta => {
        const m = s as SessionMeta
        return !!m && typeof m.id === 'string' && typeof m.updatedAt === 'number'
      })
      .sort((a: SessionMeta, b: SessionMeta) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_SESSIONS)
  } catch {
    return []
  }
}

/**
 * 登记/更新会话。
 * @param touch 为 true 时更新 updatedAt（会话列表按时间排序的依据）。
 *   仅在「该会话产生了新消息」时传 true；hello 认领/刷新恢复一律 false，
 *   否则 merely 打开一个旧会话就会把它顶到列表首位。
 */
export function upsertSession(id: string, title?: string, touch = false) {
  if (!id) return
  const all = listSessions()
  const list = all.filter((s) => s.id !== id)
  const prev = all.find((s) => s.id === id)
  const next: SessionMeta = {
    id,
    title: title ?? prev?.title ?? '新会话',
    updatedAt: touch ? Date.now() : (prev?.updatedAt ?? Date.now()),
  }
  persist([next, ...list])
}

export function removeSession(id: string) {
  persist(listSessions().filter((s) => s.id !== id))
}

/**
 * 会话迁移：服务端认领失败（重启/闲置回收）静默换了 session_id 时，
 * 让新 id 顶替旧条目 —— 标题与 updatedAt 原样继承，侧栏位置不变，旧条目删除。
 * 这样「点开一个失效的旧会话」在侧栏看来毫无动静（DeepSeek 式行为）。
 */
export function migrateSession(oldId: string, newId: string) {
  if (!oldId || !newId || oldId === newId) return
  const all = listSessions()
  const old = all.find((s) => s.id === oldId)
  if (!old) return
  const rest = all.filter((s) => s.id !== oldId && s.id !== newId)
  persist([{ id: newId, title: old.title, updatedAt: old.updatedAt }, ...rest])
}

function persist(sessions: SessionMeta[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ version: 1, sessions }))
  } catch {
    /* 静默降级 */
  }
}

/** 侧栏分组标签：今天 / 昨天 / 更早 */
export function groupLabel(ts: number): string {
  const d = new Date(ts)
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (ts >= startOfToday) return '今天'
  if (ts >= startOfToday - 86400_000) return '昨天'
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

/** 分组（保持插入顺序） */
export function groupSessions(sessions: SessionMeta[]): { label: string; items: SessionMeta[] }[] {
  const groups: { label: string; items: SessionMeta[] }[] = []
  for (const s of sessions) {
    const label = groupLabel(s.updatedAt)
    const g = groups.find((x) => x.label === label)
    if (g) g.items.push(s)
    else groups.push({ label, items: [s] })
  }
  return groups
}
