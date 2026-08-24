import { useState } from 'react'
import { useAgentStore, formatToolResult } from '../store'

/**
 * 工具日志面板：tool_start / tool_end 时间线（可折叠卡片）。
 * 数据从 items 派生（kind === 'tool'），与聊天流共享单一事件源。
 */
export default function ToolLogPanel({ title }: { title?: string }) {
  const items = useAgentStore((s) => s.items)
  const tools = items.filter((it) => it.kind === 'tool').slice(-100).reverse()

  // 折叠状态：key = tool item uid
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})

  function toggle(uid: number) {
    setExpanded((p) => ({ ...p, [uid]: !p[uid] }))
  }

  return (
    <div className="panel tool-panel">
      <div className="panel-head">
        <span>{title ?? '工具日志'}</span>
        <span className="muted">{tools.length} 次</span>
      </div>
      <div className="tool-list">
        {tools.length === 0 && <p className="empty">暂无工具调用。</p>}
        {tools.map((it) => (
          <div
            key={it.uid}
            className={`tool-entry ${it.done ? '' : 'running'}`}
            onClick={() => toggle(it.uid)}
          >
            <div className="tool-entry-head">
              <span className="tool-name">
                {it.done ? '✓' : '⏳'} {it.name}
              </span>
              {it.done ? (
                typeof it.elapsed === 'number' && (
                  <span className="elapsed-badge">{it.elapsed}s</span>
                )
              ) : (
                <span className="elapsed-badge">运行中…</span>
              )}
            </div>
            <div className={`tool-body ${expanded[it.uid] ? '' : 'closed'}`}>
              <div className="tool-args">{it.text}</div>
              {it.done && <pre className="tool-result">{formatToolResult(it.result, 300)}</pre>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
