import { useEffect } from 'react'
import { connect } from './lib/ws'
import { useAgentStore } from './store'
import { useUIStore, MODE_LABEL, type UIMode } from './uiStore'
import { loadAppearance, applyAppearance } from './lib/appearance'
import SessionSidebar from './components/SessionSidebar'
import SettingsModal from './components/SettingsModal'
import ChatPanel from './components/ChatPanel'
import ToolLogPanel from './components/ToolLogPanel'
import PetOverlay from './components/PetOverlay'

/**
 * P3 改版布局：
 * - 顶栏（磨砂）：☰ + 品牌 | 三模式切换器 | 运行状态/耗时/会话ID/连接点
 * - 左：会话侧栏（可折叠）· 中：对话主区（演示模式居中放大）· 右：工具面板（可收成细条）
 * - 背景层支持自定义图片 + 半透明蒙版 + 模糊（见 lib/appearance.ts）
 */
export default function App() {
  const connected = useAgentStore((s) => s.connected)
  const sessionId = useAgentStore((s) => s.sessionId)
  const running = useAgentStore((s) => s.running)
  const lastStatus = useAgentStore((s) => s.lastStatus)
  const lastAnswerElapsed = useAgentStore((s) => s.lastAnswerElapsed)
  const items = useAgentStore((s) => s.items)

  const mode = useUIStore((s) => s.mode)
  const sidebarOpen = useUIStore((s) => s.sidebarOpen)
  const toolsOpen = useUIStore((s) => s.toolsOpen)
  const setMode = useUIStore((s) => s.setMode)
  const toggleSidebar = useUIStore((s) => s.toggleSidebar)
  const toggleTools = useUIStore((s) => s.toggleTools)

  useEffect(() => {
    connect()
    applyAppearance(loadAppearance())
  }, [])

  const runningTool = [...items].reverse().find((it) => it.kind === 'tool' && !it.done)

  return (
    <div className={`app mode-${mode}`}>
      <div className="app-bg" aria-hidden />

      <header className="topbar">
        <div className="topbar-left">
          <button
            className="icon-btn"
            onClick={toggleSidebar}
            title={sidebarOpen ? '收起会话侧栏' : '展开会话侧栏'}
          >
            ☰
          </button>
          <div className="brand">
            <span className="brand-dot" />
            <span className="brand-title">MiniAgent</span>
          </div>
        </div>

        <div className="mode-switcher" role="tablist">
          {(['focus', 'debug', 'present'] as UIMode[]).map((m) => (
            <button
              key={m}
              className={`mode-btn ${mode === m ? 'active' : ''}`}
              onClick={() => setMode(m)}
              title={
                m === 'focus'
                  ? '专注：只保留对话'
                  : m === 'debug'
                    ? '调试：全部面板展开'
                    : '演示：居中大字号'
              }
            >
              {MODE_LABEL[m]}
            </button>
          ))}
        </div>

        <div className="topbar-right">
          {running ? (
            <span className="topbar-status running-text">
              ⏳ {runningTool ? `执行工具 ${runningTool.name}` : lastStatus || '运行中…'}
            </span>
          ) : (
            lastAnswerElapsed != null && (
              <span className="topbar-status muted">上次 {lastAnswerElapsed}s</span>
            )
          )}
          {sessionId && <code className="sid">{sessionId.slice(0, 8)}…</code>}
          <span className={`dot ${connected ? 'ok' : 'off'}`} />
          <span className="conn">{connected ? '已连接' : '连接中…'}</span>
        </div>
      </header>

      <main className={`workspace ${sidebarOpen ? '' : 'no-sidebar'}`}>
        {sidebarOpen && <SessionSidebar />}
        <section className="chat-region">
          <ChatPanel />
        </section>
        {toolsOpen ? (
          <aside className="tools-pane">
            <div className="tools-pane-inner">
              <ToolLogPanel />
            </div>
            <button className="tools-collapse" onClick={toggleTools} title="收起工具面板">
              »
            </button>
          </aside>
        ) : (
          <button className="tools-rail" onClick={toggleTools} title="展开工具日志">
            <span className="tools-rail-icon">🛠</span>
          </button>
        )}
      </main>

      <SettingsModal />
      <PetOverlay />
    </div>
  )
}
