import { useState } from 'react'
import { useAgentStore } from '../store'
import { listSessions, groupSessions, removeSession, type SessionMeta } from '../lib/sessions'
import { deleteTranscript } from '../lib/transcripts'
import { useUIStore } from '../uiStore'

/**
 * 会话侧栏：新会话按钮 + 历史（今天/昨天/更早分组）+ 当前会话高亮。
 * 数据来自 localStorage 注册表，服务端 hello 认领后刷新即可见。
 */
export default function SessionSidebar() {
  const sessionId = useAgentStore((s) => s.sessionId)
  const running = useAgentStore((s) => s.running)
  const setSettingsOpen = useUIStore((s) => s.setSettingsOpen)

  // items 变化时（hello / 用户发言）注册表会被更新，这里订阅一个低频信号即可
  useAgentStore((s) => s.items.length)

  // 空会话（从未发过消息，标题仍是默认值）不展示；当前会话始终保留以便定位
  // 排序完全依赖 listSessions() 的 updatedAt 降序 —— 不做任何「当前会话置顶」操作
  const isEmpty = (s: SessionMeta) => s.title === '新会话'
  const visible = listSessions().filter((s) => s.id === sessionId || !isEmpty(s))
  const groups = groupSessions(visible)

  function openSession(id: string) {
    if (id === sessionId) return
    localStorage.setItem('miniagent_sid', id)
    location.reload()
  }

  function newSession() {
    localStorage.removeItem('miniagent_sid')
    location.reload()
  }

  /** 删除会话：清注册表条目 + 本地转录缓存；删的是当前会话则顺带开新会话。 */
  function deleteSession(s: SessionMeta) {
    removeSession(s.id)
    deleteTranscript(s.id)
    if (s.id === sessionId) {
      localStorage.removeItem('miniagent_sid')
    }
    location.reload()
  }

  return (
    <aside className="session-sidebar">
      <button
        className="btn new-chat-btn"
        onClick={newSession}
        disabled={running}
        title={running ? 'Agent 运行中…' : '开启新会话'}
      >
        ＋ 新会话
      </button>

      <div className="session-list">
        {groups.length === 0 && <p className="empty">还没有历史会话</p>}
        {groups.map((g) => (
          <div key={g.label} className="session-group">
            <div className="session-group-label">{g.label}</div>
            {g.items.map((s) => (
              <SessionRow
                key={s.id}
                s={s}
                active={s.id === sessionId}
                disabled={running && s.id !== sessionId}
                onClick={() => openSession(s.id)}
                onDelete={() => deleteSession(s)}
                deleteDisabled={running}
              />
            ))}
          </div>
        ))}
      </div>

      <div className="session-footer">
        <button className="session-footer-btn" onClick={() => setSettingsOpen(true)}>
          ⚙ 外观设置
        </button>
      </div>
    </aside>
  )
}

function SessionRow({
  s,
  active,
  disabled,
  onClick,
  onDelete,
  deleteDisabled,
}: {
  s: SessionMeta
  active: boolean
  disabled?: boolean
  onClick: () => void
  onDelete: () => void
  deleteDisabled?: boolean
}) {
  // 两步确认：第一次点 ✕ 进入「确认删除」状态（3 秒自动复原），再点一次才真删
  const [arming, setArming] = useState(false)
  const [timer, setTimer] = useState<ReturnType<typeof setTimeout> | null>(null)

  function handleDeleteClick() {
    if (!arming) {
      setArming(true)
      if (timer) clearTimeout(timer)
      setTimer(setTimeout(() => setArming(false), 3000))
      return
    }
    if (timer) clearTimeout(timer)
    onDelete()
  }

  return (
    <div className={`session-row ${active ? 'active' : ''}`}>
      <button
        className="session-item"
        onClick={onClick}
        disabled={disabled}
        title={s.title}
      >
        <span className="session-item-title">{s.title}</span>
        {active && <span className="session-item-dot" />}
      </button>
      <button
        className={`session-del ${arming ? 'arming' : ''}`}
        onClick={(e) => {
          e.stopPropagation()
          handleDeleteClick()
        }}
        disabled={deleteDisabled}
        title={deleteDisabled ? 'Agent 运行中，稍后再删' : arming ? '再点一次确认删除' : '删除该会话'}
        aria-label="删除会话"
      >
        {arming ? '确认' : '✕'}
      </button>
    </div>
  )
}
