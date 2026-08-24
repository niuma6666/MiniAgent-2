import { useEffect, useRef, useState } from 'react'
import { useAgentStore } from '../store'
import { renderMarkdown } from '../lib/markdown'
import { send } from '../lib/ws'
import ToolCard from './ToolCard'

/**
 * 聊天主面板（P3 改版）：
 * - 头部「新会话」移至会话侧栏，这里只保留对话本体；
 * - 工具调用以 ToolCard 渐进披露呈现；
 * - 保留 confirm 弹窗 / 流式渲染 / running 禁用语义；
 * - 等待期（发出后 → 首个事件前）显示思考小动画，告诉用户「系统还活着」。
 */

const THINKING_LABELS = ['正在唤醒大脑…', '认真思考中…', '翻一翻工具箱…', '组织语言…']

export default function ChatPanel() {
  const items = useAgentStore((s) => s.items)
  const running = useAgentStore((s) => s.running)
  const connected = useAgentStore((s) => s.connected)
  const pendingConfirm = useAgentStore((s) => s.pendingConfirm)
  const clearPendingConfirm = useAgentStore((s) => s.clearPendingConfirm)
  const userSent = useAgentStore((s) => s.userSent)

  const [input, setInput] = useState('')
  const [labelIdx, setLabelIdx] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)

  // 等待期：运行中，但本轮还没收到任何事件（最后一条是用户消息，或列表为空）
  const waiting =
    running && (items.length === 0 || items[items.length - 1].kind === 'user')

  useEffect(() => {
    if (!waiting) return
    const t = window.setInterval(() => setLabelIdx((i) => i + 1), 2400)
    return () => window.clearInterval(t)
  }, [waiting])

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [items])

  function handleSend() {
    const text = input.trim()
    if (!text || running || !connected) return
    setInput('')
    userSent(text)
    send({ type: 'chat', text })
  }

  function confirmAnswer(allow: boolean) {
    if (pendingConfirm.id) {
      send({ type: 'confirm_response', id: pendingConfirm.id, allow })
    }
    clearPendingConfirm()
  }

  return (
    <div className="panel chat-panel">
      <div className="chat-list" ref={listRef}>
        {items.length === 0 && (
          <div className="chat-welcome">
            <div className="chat-welcome-logo">MA</div>
            <div className="chat-welcome-title">MiniAgent</div>
            <div className="chat-welcome-sub">输入一条指令开始，工具调用会以卡片形式展示。</div>
          </div>
        )}
        {items.map((it) => {
          if (it.kind === 'answer') {
            return (
              <div
                key={it.uid}
                className="md answer"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(it.text) }}
              />
            )
          }
          if (it.kind === 'tool') {
            return <ToolCard key={it.uid} item={it} />
          }
          if (it.kind === 'status') {
            return (
              <div key={it.uid} className="status-line">
                … {it.text}
              </div>
            )
          }
          if (it.kind === 'error') {
            return (
              <div key={it.uid} className="error-line">
                ❌ {it.text}
              </div>
            )
          }
          if (it.kind === 'notice') {
            return (
              <div key={it.uid} className="notice-line">
                ⓘ {it.text}
              </div>
            )
          }
          return (
            <div key={it.uid} className="user-line">
              {it.text}
            </div>
          )
        })}

        {waiting && (
          <div className="thinking-indicator" aria-live="polite">
            <span className="ti-avatar">🤖</span>
            <span className="ti-bubble">
              <span className="ti-dots">
                <i />
                <i />
                <i />
              </span>
              <span className="ti-label" key={labelIdx}>
                {THINKING_LABELS[labelIdx % THINKING_LABELS.length]}
              </span>
            </span>
          </div>
        )}
      </div>

      <div className="chat-input">
        <input
          value={input}
          placeholder={
            running ? 'Agent 运行中…' : connected ? '输入指令，Enter 发送' : '连接中…'
          }
          disabled={running || !connected}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSend()
          }}
        />
        <button className="btn primary" onClick={handleSend} disabled={running || !connected}>
          {running ? '运行中…' : '发送'}
        </button>
      </div>

      {pendingConfirm.id && (
        <div className="confirm-overlay">
          <div className="confirm-box">
            <div className="c-title">⚠️ Agent 请求确认</div>
            <div className="c-desc">{pendingConfirm.desc}</div>
            <div className="c-actions">
              <button className="btn allow" onClick={() => confirmAnswer(true)}>
                允许
              </button>
              <button className="btn deny" onClick={() => confirmAnswer(false)}>
                拒绝
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
