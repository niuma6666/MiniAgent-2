import { useState } from 'react'
import type { ChatItem } from '../store'
import { formatToolResult } from '../store'

/**
 * 聊天内联工具卡片（渐进披露）：
 * 收起 = 图标 + 工具名 + 参数摘要 + 耗时徽章；点击展开 args / result 详情。
 */
export default function ToolCard({ item }: { item: ChatItem }) {
  const [open, setOpen] = useState(false)
  const running = !item.done

  const summary = summarizeArgs(item.text)
  const elapsed =
    item.done && typeof item.elapsed === 'number' ? `${item.elapsed}s` : running ? '运行中' : ''

  return (
    <div className={`tool-card ${running ? 'running' : ''} ${open ? 'open' : ''}`}>
      <button className="tool-card-head" onClick={() => setOpen(!open)} title="点击展开详情">
        <span className="tool-card-icon">{running ? '⏳' : '✓'}</span>
        <span className="tool-card-name">{item.name}</span>
        <span className="tool-card-summary">{summary}</span>
        {elapsed && (
          <span className={`tool-card-badge ${running ? 'running' : ''}`}>{elapsed}</span>
        )}
        <span className="tool-card-chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="tool-card-body">
          <div className="tool-card-sec">
            <div className="tool-card-sec-label">参数</div>
            <pre className="tool-card-code">{item.text || '（无）'}</pre>
          </div>
          {item.done && (
            <div className="tool-card-sec">
              <div className="tool-card-sec-label">结果</div>
              <pre className="tool-card-code">{formatToolResult(item.result, 600)}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function summarizeArgs(text: string): string {
  const t = (text || '').replace(/\s+/g, ' ').trim()
  if (!t) return ''
  return t.length > 48 ? t.slice(0, 48) + '…' : t
}
