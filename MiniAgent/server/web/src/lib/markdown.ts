import { marked } from 'marked'

/**
 * markdown 渲染：marked 渲染 → 消毒 → 输出；异常时退回转义纯文本。
 * - 渲染前剥离开头 FINAL_ANSWER: 前缀（模型"一稿两写"的显示消除）；
 * - marked 不自带消毒，输出会进 dangerouslySetInnerHTML，
 *   必须过滤 script/iframe/style 块、on* 事件属性、javascript: 协议
 *   （模型输出或搜索结果里可能夹带，防 XSS）。
 */

export function renderMarkdown(md: string): string {
  const text = stripFinalAnswerPrefix(md)
  try {
    return sanitizeHtml(marked.parse(text, { breaks: true }) as string)
  } catch {
    return escapeHtml(text)
  }
}

/** 最小化 HTML 消毒（marked 输出专用，流式半截标签也要防） */
function sanitizeHtml(html: string): string {
  return html
    .replace(/<(script|style|iframe|object|embed)[\s\S]*?<\/\1\s*>/gi, '')
    .replace(/<(script|style|iframe|object|embed)\b/gi, '&lt;$1') // 流式中未闭合的标签
    .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '') // on* 事件属性
    .replace(/(href|src)\s*=\s*(["'])\s*javascript:[^"']*\2/gi, '$1=$2#$2')
}

export function stripFinalAnswerPrefix(s: string): string {
  return s.replace(/^\s*FINAL_ANSWER:\s*/i, '')
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
