import { useEffect, useRef, useState } from 'react'
import { onAgentEvent } from '../store'

/**
 * 小金鱼桌宠 · 仪表盘悬浮版（阶段 2 嵌入）
 *
 * - 复用仪表盘现有 WS 连接（store.applyEvent 的 onAgentEvent 钩子），不再开第二条连接；
 * - v2 形象（用户定稿：侧身水滴鱼）+ 六状态 FSM：
 *   hello.running / status(Thinking…) → thinking
 *   tool_start → working（尾巴摆快）  tool_end → thinking
 *   stream → speaking（嘴动 + 文字气泡）
 *   confirm_request → waiting_confirm（只展示，按钮在仪表盘确认弹窗）
 *   done → happy    error → error
 * - happy 2.6s / error 5s / waiting_confirm 65s 自动回 idle；
 * - 双姿态：平时侧脸绕圈游，互动时刻（thinking/happy/waiting_confirm/卖萌）切正脸；
 * - 点小鱼随机卖萌台词（2.8s 消失）；
 * - 右下角悬浮，hover 出 ✕ 可隐藏，隐藏后右下角出现 🐟 恢复按钮。
 */

type PetState = 'idle' | 'thinking' | 'working' | 'speaking' | 'waiting_confirm' | 'happy' | 'error'

const STATE_TIMEOUTS: Partial<Record<PetState, number>> = {
  happy: 2600,
  error: 5000,
  waiting_confirm: 65000,
}

/** 点击小鱼随机卖萌的台词 */
const CUTE_LINES = [
  '咕噜咕噜～',
  '今天也要加油鸭！',
  '我只是一条小鱼…只会卖萌',
  '你在看什么呀？',
  '咘噜～',
  '尾巴摇一摇，烦恼全跑掉',
  '猜猜我在想什么？',
  '水里有好多秘密哦',
  '喂，别走神，看我～',
  '吐个泡泡给你呀',
  '认真工作的鱼最帅！',
  '咕…饿了，但我不说',
]

export default function PetOverlay() {
  const [state, setState] = useState<PetState>('idle')
  const [speech, setSpeech] = useState('')
  const [confirmDesc, setConfirmDesc] = useState('')
  const [hidden, setHidden] = useState(false)
  const [cute, setCute] = useState<string | null>(null)
  const cuteTimer = useRef<number | null>(null)
  const lastCuteIdx = useRef(-1)

  /** 点击小鱼：随机卖萌台词（避开上一条），2.8s 后消失 */
  function handlePetClick() {
    let i = Math.floor(Math.random() * CUTE_LINES.length)
    if (i === lastCuteIdx.current) i = (i + 1) % CUTE_LINES.length
    lastCuteIdx.current = i
    setCute(CUTE_LINES[i])
    if (cuteTimer.current) window.clearTimeout(cuteTimer.current)
    cuteTimer.current = window.setTimeout(() => setCute(null), 2800)
  }

  // 卸载时清理卖萌定时器
  useEffect(() => {
    return () => {
      if (cuteTimer.current) window.clearTimeout(cuteTimer.current)
    }
  }, [])

  useEffect(() => {
    const off = onAgentEvent((e) => {
      switch (e.type) {
        case 'hello':
          if (e.running === true) setState('thinking')
          break
        case 'status':
          if (typeof e.text === 'string' && e.text.startsWith('Thinking')) setState('thinking')
          break
        case 'tool_start':
          setState('working')
          break
        case 'tool_end':
          setState('thinking')
          break
        case 'stream':
          setState('speaking')
          setSpeech((s) => (s + String(e.token ?? '')).slice(-60))
          break
        case 'confirm_request':
          setConfirmDesc(String(e.desc ?? ''))
          setState('waiting_confirm')
          break
        case 'done':
          setState('happy')
          break
        case 'error':
          setState('error')
          break
      }
    })
    return off
  }, [])

  // 状态自动回落 idle
  useEffect(() => {
    const t = STATE_TIMEOUTS[state]
    if (!t) return
    const id = window.setTimeout(() => setState((s) => (s === state ? 'idle' : s)), t)
    return () => window.clearTimeout(id)
  }, [state])

  // 离开 speaking 清空文字
  useEffect(() => {
    if (state !== 'speaking') setSpeech('')
  }, [state])

  // 双姿态：互动时刻（思考/开心/等你确认/卖萌）切正脸，其余侧脸游
  const frontFace =
    state === 'thinking' || state === 'happy' || state === 'waiting_confirm' || cute !== null

  if (hidden) {
    return (
      <button className="petx-restore" onClick={() => setHidden(false)} title="显示小金鱼">
        🐟
      </button>
    )
  }

  return (
    <div
      className={`petx-root petx-state-${state}${frontFace ? ' petx-face-front' : ''}`}
      data-state={state}
    >
      <button className="petx-close" onClick={() => setHidden(true)} title="隐藏小金鱼">
        ×
      </button>

      <div className="petx-fx petx-fx-thinking">
        <span className="petx-gear">⚙</span>思考中…
      </div>
      <div className="petx-fx petx-fx-working">
        <span className="petx-wrench">🔧</span>干活中…
      </div>
      <div className="petx-fx petx-fx-speaking">
        <span>💬</span>
        <span className="petx-speech">{speech}</span>
      </div>
      <div className="petx-fx petx-fx-happy">
        <span className="petx-heart">💗</span>完成！
      </div>
      <div className="petx-fx petx-fx-error">
        <span className="petx-sweat">💧</span>出错了…
      </div>
      <div className="petx-confirm">
        <div className="petx-q">🤔 需要你确认</div>
        <div className="petx-desc">{confirmDesc}</div>
      </div>

      {cute && <div className="petx-cute">{cute}</div>}

      <div className="petx-fish" onClick={handlePetClick} title="点我一下～">
        <div className="petx-side-wrap">
          <div className="petx-mirror">
            <svg className="petx-side" viewBox="0 0 300 220" role="img" aria-label="会游动的小金鱼">
          <defs>
            <linearGradient id="petx-g-body" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#FFD36B" />
              <stop offset="18%" stopColor="#FF8C00" />
              <stop offset="52%" stopColor="#D97A14" />
              <stop offset="78%" stopColor="#FFE0C0" />
              <stop offset="100%" stopColor="#FFF5E6" />
            </linearGradient>
            <linearGradient id="petx-g-tail" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#CC6600" />
              <stop offset="70%" stopColor="#FF8C00" />
              <stop offset="100%" stopColor="#FFB380" />
            </linearGradient>
            <linearGradient id="petx-g-fin" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#FFB380" />
              <stop offset="100%" stopColor="#FF8C00" />
            </linearGradient>
            <radialGradient id="petx-g-iris" cx="0.5" cy="0.45" r="0.6">
              <stop offset="0%" stopColor="#7A4E24" />
              <stop offset="70%" stopColor="#5C3A1C" />
              <stop offset="100%" stopColor="#3A2410" />
            </radialGradient>
            <linearGradient id="petx-g-rainbow" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#FF9EB5" />
              <stop offset="35%" stopColor="#9ED8FF" />
              <stop offset="70%" stopColor="#B8F0C0" />
              <stop offset="100%" stopColor="#FFE08A" />
            </linearGradient>
            <radialGradient id="petx-g-shadow">
              <stop offset="0%" stopColor="rgba(120,110,100,0.4)" />
              <stop offset="100%" stopColor="rgba(120,110,100,0)" />
            </radialGradient>
          </defs>

          <g id="petx-shadow">
            <ellipse cx="140" cy="190" rx="88" ry="10" fill="url(#petx-g-shadow)" opacity="0.5" />
          </g>

          <g id="petx-tail" className="petx-part">
            <path
              d="M 182 108 C 196 60, 230 50, 254 70 C 265 80, 264 96, 250 104 C 260 108, 264 122, 254 132 C 230 154, 196 148, 182 108 Z"
              fill="url(#petx-g-tail)"
              opacity="0.92"
            />
            <path d="M 186 108 C 214 100, 238 98, 252 102" stroke="#FFE0B8" strokeWidth="2" fill="none" opacity="0.7" />
          </g>

          <g id="petx-fin-belly" className="petx-part">
            <path
              d="M 128 150 C 126 164, 134 170, 142 168 C 148 166, 146 156, 140 150 Z"
              fill="url(#petx-g-fin)"
              opacity="0.7"
            />
          </g>

          <g id="petx-fin-chest" className="petx-part">
            <path d="M 98 136 C 88 152, 92 164, 104 164 C 114 164, 116 152, 110 140 Z" fill="#FF9A50" opacity="0.6" />
            <path d="M 102 140 C 96 150, 98 158, 105 159 C 111 160, 112 152, 108 144 Z" fill="#FFDAB9" opacity="0.7" />
          </g>

          <g id="petx-fin-top" className="petx-part">
            <path
              d="M 138 68 C 142 46, 158 40, 168 48 C 174 53, 172 62, 164 66 C 158 69, 146 70, 138 68 Z"
              fill="url(#petx-g-fin)"
              opacity="0.8"
            />
            <path
              d="M 142 62 L 146 56 L 150 62 L 155 54 L 159 62 L 164 55 L 167 62"
              stroke="#FFD9A8"
              strokeWidth="1.6"
              fill="none"
              opacity="0.8"
            />
          </g>

          <g id="petx-body" className="petx-part">
            <path
              d="M 72 108 C 72 80, 88 66, 110 66 C 140 66, 165 74, 180 92 C 190 104, 190 112, 180 124 C 165 142, 140 150, 112 150 C 88 150, 72 136, 72 108 Z"
              fill="url(#petx-g-body)"
            />
            <path d="M 82 74 C 108 62, 150 64, 176 86 C 158 72, 118 68, 92 78 Z" fill="#B26A00" opacity="0.25" />
            <ellipse cx="118" cy="76" rx="34" ry="10" fill="#FFD700" opacity="0.35" transform="rotate(-8 118 76)" />
            <g fill="#FFB44D" stroke="#E88A2A" strokeWidth="1.2" opacity="0.55">
              <path d="M 124 88 a 11 11 0 0 0 22 0 Z" />
              <path d="M 144 92 a 10 10 0 0 0 20 0 Z" />
              <path d="M 108 96 a 10 10 0 0 0 20 0 Z" />
              <path d="M 160 98 a 9 9 0 0 0 18 0 Z" />
            </g>
          </g>

          <g id="petx-eye" className="petx-eye">
            <circle cx="92" cy="92" r="26" fill="#ffffff" />
            <circle cx="94" cy="94" r="17" fill="url(#petx-g-iris)" />
            <circle cx="95" cy="95" r="9" fill="#3A2410" />
            <circle cx="95.5" cy="95.5" r="4.5" fill="#1F1308" />
            <circle cx="88" cy="84" r="6" fill="#ffffff" />
            <circle cx="99" cy="101" r="2.6" fill="#ffffff" opacity="0.9" />
            <path
              d="M 68 84 C 74 72, 88 66, 102 72"
              stroke="#D97A14"
              strokeWidth="3"
              fill="none"
              strokeLinecap="round"
              opacity="0.8"
            />
            {/* 翻跟头时闭眼（∩ 弧线，与翻跟头同周期闪现） */}
            <g transform="translate(92 92)">
              <path className="petx-lid" d="M -11 0 Q 0 -9 11 0" stroke="#3A2410" strokeWidth="4" fill="none" strokeLinecap="round" />
            </g>
          </g>

          <g id="petx-blush">
            <ellipse cx="108" cy="124" rx="10" ry="6" fill="#FF9E9E" opacity="0.45" />
          </g>

          <g id="petx-mouth">
            <ellipse cx="70" cy="120" rx="5" ry="4.5" fill="#FF9EB5" />
            <path
              d="M 67 118.5 C 68 115.5, 72 115.5, 73 118.5"
              stroke="#F08CA4"
              strokeWidth="1.2"
              fill="none"
              strokeLinecap="round"
            />
          </g>

          <g id="petx-bubbles">
            <g className="petx-bubble">
              <circle cx="44" cy="94" r="15" fill="none" stroke="url(#petx-g-rainbow)" strokeWidth="2.4" opacity="0.9" />
              <circle cx="38" cy="87" r="4" fill="#ffffff" opacity="0.85" />
              <path d="M 50 88 a 5 5 0 0 1 5 3" stroke="#ffffff" strokeWidth="1.6" fill="none" opacity="0.7" />
            </g>
            <g className="petx-bubble petx-b2">
              <circle cx="36" cy="108" r="5" fill="#ffffff" opacity="0.7" stroke="#9ED8FF" strokeWidth="1" />
            </g>
            <g className="petx-bubble petx-b3">
              <circle cx="58" cy="80" r="3.6" fill="#ffffff" opacity="0.65" stroke="#B8F0C0" strokeWidth="0.8" />
            </g>
          </g>

          <g id="petx-accessory" />
            </svg>
          </div>
        </div>

        {/* 正脸姿态：互动时刻（思考/开心/确认/卖萌）淡入，平时隐藏 */}
        <svg className="petx-front" viewBox="0 0 300 220" role="img" aria-label="小金鱼正脸">
          {/* 背鳍 */}
          <g id="petx-f-fin-top" className="petx-part">
            <path
              d="M 132 58 C 136 34, 164 34, 168 58 C 156 50, 144 50, 132 58 Z"
              fill="url(#petx-g-fin)"
              opacity="0.85"
            />
          </g>
          {/* 尾巴尖（身后探出） */}
          <path
            d="M 96 150 C 84 158, 80 174, 92 180 C 102 184, 108 172, 104 160 Z"
            fill="url(#petx-g-tail)"
            opacity="0.85"
          />
          <path
            d="M 204 150 C 216 158, 220 174, 208 180 C 198 184, 192 172, 196 160 Z"
            fill="url(#petx-g-tail)"
            opacity="0.85"
          />
          {/* 胸鳍（左右） */}
          <g id="petx-f-fin-l" className="petx-part petx-f-flap">
            <path d="M 96 134 C 74 138, 64 154, 70 168 C 78 178, 92 174, 98 160 Z" fill="#FF9A50" opacity="0.6" />
            <path d="M 100 140 C 84 146, 76 158, 82 168 C 88 174, 97 170, 100 162 Z" fill="#FFDAB9" opacity="0.7" />
          </g>
          <g id="petx-f-fin-r" className="petx-part petx-f-flap">
            <path d="M 204 134 C 226 138, 236 154, 230 168 C 222 178, 208 174, 202 160 Z" fill="#FF9A50" opacity="0.6" />
            <path d="M 200 140 C 216 146, 224 158, 218 168 C 212 174, 203 170, 200 162 Z" fill="#FFDAB9" opacity="0.7" />
          </g>
          {/* 身体（圆润正脸） */}
          <g id="petx-f-body" className="petx-part">
            <path
              d="M 150 54 C 100 54, 74 78, 74 108 C 74 138, 100 162, 150 162 C 200 162, 226 138, 226 108 C 226 78, 200 54, 150 54 Z"
              fill="url(#petx-g-body)"
            />
            <ellipse cx="150" cy="70" rx="38" ry="9" fill="#FFD700" opacity="0.3" transform="rotate(-2 150 70)" />
            <g fill="#FFB44D" stroke="#E88A2A" strokeWidth="1.1" opacity="0.5">
              <path d="M 124 84 a 10 10 0 0 0 20 0 Z" />
              <path d="M 152 82 a 10 10 0 0 0 20 0 Z" />
              <path d="M 138 96 a 9 9 0 0 0 18 0 Z" />
              <path d="M 176 94 a 8 8 0 0 0 16 0 Z" />
            </g>
          </g>
          {/* 眼睛 ×2（复用眨眼动画） */}
          <g id="petx-f-eye-l" className="petx-eye">
            <circle cx="118" cy="104" r="17" fill="#ffffff" />
            <circle cx="119" cy="105" r="11" fill="url(#petx-g-iris)" />
            <circle cx="120" cy="106" r="6" fill="#3A2410" />
            <circle cx="120.5" cy="106.5" r="3" fill="#1F1308" />
            <circle cx="113" cy="98" r="3.5" fill="#ffffff" />
            <circle cx="125" cy="111" r="1.6" fill="#ffffff" opacity="0.9" />
            <path
              d="M 104 96 C 109 90, 118 88, 127 92"
              stroke="#D97A14"
              strokeWidth="2.2"
              fill="none"
              strokeLinecap="round"
              opacity="0.75"
            />
            <g transform="translate(118 104)">
              <path className="petx-lid" d="M -10 0 Q 0 -8 10 0" stroke="#3A2410" strokeWidth="3.6" fill="none" strokeLinecap="round" />
            </g>
          </g>
          <g id="petx-f-eye-r" className="petx-eye">
            <circle cx="182" cy="104" r="17" fill="#ffffff" />
            <circle cx="181" cy="105" r="11" fill="url(#petx-g-iris)" />
            <circle cx="180" cy="106" r="6" fill="#3A2410" />
            <circle cx="179.5" cy="106.5" r="3" fill="#1F1308" />
            <circle cx="175" cy="98" r="3.5" fill="#ffffff" />
            <circle cx="187" cy="111" r="1.6" fill="#ffffff" opacity="0.9" />
            <path
              d="M 173 96 C 182 90, 191 92, 196 96"
              stroke="#D97A14"
              strokeWidth="2.2"
              fill="none"
              strokeLinecap="round"
              opacity="0.75"
            />
            <g transform="translate(182 104)">
              <path className="petx-lid" d="M -10 0 Q 0 -8 10 0" stroke="#3A2410" strokeWidth="3.6" fill="none" strokeLinecap="round" />
            </g>
          </g>
          {/* 腮红 */}
          <g id="petx-f-blush">
            <ellipse cx="100" cy="132" rx="9" ry="6" fill="#FF9E9E" opacity="0.45" />
            <ellipse cx="200" cy="132" rx="9" ry="6" fill="#FF9E9E" opacity="0.45" />
          </g>
          {/* 嘴：ω 笑 */}
          <g id="petx-f-mouth">
            <path d="M 140 130 Q 145 137 150 130 Q 155 137 160 130" stroke="#E87A96" strokeWidth="2.6" fill="none" strokeLinecap="round" />
          </g>
          <g id="petx-f-accessory" />
        </svg>
      </div>

      <style>{`
        .petx-root {
          position: fixed;
          right: 18px;
          bottom: 14px;
          width: 158px;
          height: 128px;
          z-index: 60;
          pointer-events: none;
          user-select: none;
        }
        .petx-root .petx-fish {
          position: absolute;
          right: 0;
          bottom: 0;
          width: 150px;
          height: 110px;
          filter: drop-shadow(0 2px 6px rgba(61, 50, 46, 0.12));
          pointer-events: auto;
          cursor: pointer;
        }
        .petx-root .petx-fish svg {
          width: 100%;
          height: 100%;
          overflow: visible;
          will-change: transform;
        }
        /* 侧脸：水平 3D 错觉绕圈（默认）——沿扁椭圆平移 + 近大远小；
           方向镜像由 .petx-mirror 用 steps() 在两端点瞬切（避免缩放插值压扁鱼）；
           翻跟头由外层 .petx-side-wrap 负责 */
        .petx-root .petx-fish svg.petx-side {
          animation: petx-swim 7s linear infinite;
        }
        /* 方向镜像：左半圈面朝左，右半圈面朝右（steps 瞬切，在两端点转身） */
        .petx-root .petx-mirror {
          position: absolute;
          inset: 0;
          animation: petx-mirror 7s steps(1) infinite;
        }
        @keyframes petx-mirror {
          0%   { transform: scaleX(1); }
          50%  { transform: scaleX(-1); }
          100% { transform: scaleX(1); }
        }
        /* 翻跟头：绕侧脸容器中心每 ~17s 快速转一圈 */
        .petx-root .petx-side-wrap {
          position: absolute;
          inset: 0;
          transform-origin: 56% 50%;
          animation: petx-roll 17s ease-in-out infinite;
        }
        @keyframes petx-roll {
          0%, 91% { transform: rotate(0deg); }
          97%     { transform: rotate(360deg); }
          100%    { transform: rotate(360deg); }
        }
        /* 翻转时闭眼：>_< 风格的弧线，与翻跟头同周期闪现 */
        .petx-root .petx-lid {
          opacity: 0;
          animation: petx-lid 17s ease-in-out infinite;
        }
        @keyframes petx-lid {
          0%, 90% { opacity: 0; }
          93%, 96% { opacity: 1; }
          100%    { opacity: 0; }
        }
        /* 正脸：轻柔浮动，平时透明隐藏；petx-face-front 时淡入 */
        .petx-root .petx-fish svg.petx-front {
          position: absolute;
          inset: 0;
          opacity: 0;
          pointer-events: none;
          transition: opacity 0.35s ease;
          animation: petx-bob 3.4s ease-in-out infinite;
        }
        .petx-root.petx-face-front .petx-fish svg.petx-side { opacity: 0; }
        .petx-root.petx-face-front .petx-fish svg.petx-front { opacity: 1; }
        @keyframes petx-bob {
          0%, 100% { transform: translateY(0); }
          50%      { transform: translateY(-6px); }
        }
        /* 正脸胸鳍：轻柔扑动 */
        .petx-root .petx-f-flap {
          transform-origin: 50% 0%;
          animation: petx-f-flap 1.9s ease-in-out infinite;
        }
        .petx-root #petx-f-fin-r { animation-direction: reverse; }
        @keyframes petx-f-flap {
          0%, 100% { transform: rotate(-7deg); }
          50%      { transform: rotate(8deg); }
        }
        /* 水平 3D 错觉绕圈：扁椭圆轨迹（rx 26 / ry 12）+ 近大远小
           （底部近处 scale 1.14，顶部远处 0.86）；朝左默认、朝右靠镜像层 */
        @keyframes petx-swim {
          0%    { transform: translate(26px, 0) scale(1, 1); }
          12.5% { transform: translate(18.4px, 8.5px) scale(1.1, 1.1); }
          25%   { transform: translate(0, 12px) scale(1.14, 1.14); }
          37.5% { transform: translate(-18.4px, 8.5px) scale(1.1, 1.1); }
          50%   { transform: translate(-26px, 0) scale(1, 1); }
          62.5% { transform: translate(-18.4px, -8.5px) scale(0.9, 0.9); }
          75%   { transform: translate(0, -12px) scale(0.86, 0.86); }
          87.5% { transform: translate(18.4px, -8.5px) scale(0.9, 0.9); }
          100%  { transform: translate(26px, 0) scale(1, 1); }
        }

        .petx-root .petx-part { transform-box: fill-box; will-change: transform; }
        .petx-root #petx-tail { transform-origin: 0% 50%; animation: petx-wag 1.3s ease-in-out infinite; }
        @keyframes petx-wag {
          0%, 100% { transform: rotate(-16deg); }
          50%      { transform: rotate(14deg); }
        }
        .petx-root.petx-state-working #petx-tail { animation-duration: 0.7s; }
        .petx-root #petx-fin-top { transform-origin: 50% 100%; animation: petx-fintop 2.6s ease-in-out infinite; }
        @keyframes petx-fintop {
          0%, 100% { transform: rotate(-5deg) scaleY(1); }
          50%      { transform: rotate(7deg) scaleY(0.9); }
        }
        .petx-root #petx-fin-chest,
        .petx-root #petx-fin-belly { transform-origin: 50% 0%; animation: petx-finflap 1.7s ease-in-out infinite; }
        .petx-root #petx-fin-belly { animation-duration: 2.2s; animation-direction: reverse; }
        @keyframes petx-finflap {
          0%, 100% { transform: rotate(-10deg); }
          50%      { transform: rotate(10deg); }
        }
        .petx-root #petx-body { transform-origin: center; animation: petx-squash 4.2s ease-in-out infinite; }
        @keyframes petx-squash {
          0%, 100% { transform: rotate(-2deg) scale(1, 1); }
          50%      { transform: rotate(-2deg) scale(1.015, 0.965); }
        }
        .petx-root .petx-eye { transform-origin: center; animation: petx-blink 4.6s ease-in-out infinite; }
        @keyframes petx-blink {
          0%, 91%, 100% { transform: scaleY(1); }
          94%           { transform: scaleY(0.08); }
          97%           { transform: scaleY(1); }
        }
        .petx-root #petx-blush { transform-origin: center; animation: petx-blushp 4.2s ease-in-out infinite; }
        @keyframes petx-blushp {
          0%, 100% { opacity: 0.3; }
          50%      { opacity: 0.5; }
        }
        .petx-root #petx-shadow { transform-origin: center; animation: petx-shadowb 4.2s ease-in-out infinite; }
        @keyframes petx-shadowb {
          0%, 100% { transform: scale(1, 1); opacity: 0.85; }
          50%      { transform: scale(0.93, 0.85); opacity: 0.6; }
        }
        .petx-root.petx-state-speaking #petx-mouth { animation: petx-talk 0.45s ease-in-out infinite; }
        @keyframes petx-talk {
          0%, 100% { transform: scaleY(0.55); }
          50%      { transform: scaleY(1.45); }
        }
        .petx-root .petx-bubble {
          transform-box: fill-box;
          transform-origin: center;
          animation: petx-bdrift 4.6s ease-in-out infinite;
        }
        .petx-root .petx-b2 { animation-delay: 1.5s; animation-duration: 5.2s; }
        .petx-root .petx-b3 { animation-delay: 3.1s; animation-duration: 4s; }
        @keyframes petx-bdrift {
          0%   { transform: translate(0, 0) scale(0.9); opacity: 0; }
          15%  { opacity: 0.9; }
          60%  { opacity: 0.55; }
          100% { transform: translate(-16px, -26px) scale(1.06); opacity: 0; }
        }

        /* 状态特效层 */
        .petx-root .petx-fx {
          position: absolute;
          display: none;
          align-items: center;
          gap: 4px;
          font-size: 11px;
          color: var(--text-2, #8c7e76);
          background: rgba(255, 255, 255, 0.92);
          border: 1px solid rgba(61, 50, 46, 0.08);
          border-radius: 999px;
          padding: 4px 10px;
          box-shadow: 0 2px 8px rgba(122, 52, 31, 0.08);
          white-space: nowrap;
          max-width: 190px;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .petx-root .petx-gear { display: inline-block; animation: petx-spin 2.4s linear infinite; font-size: 13px; }
        @keyframes petx-spin { to { transform: rotate(360deg); } }
        .petx-root .petx-wrench { display: inline-block; animation: petx-bob 0.8s ease-in-out infinite; font-size: 13px; }
        @keyframes petx-bob { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-2px); } }
        .petx-root .petx-heart { display: inline-block; animation: petx-heartup 1.6s ease-in-out infinite; font-size: 15px; }
        @keyframes petx-heartup {
          0%   { transform: translateY(3px) scale(0.8); opacity: 0; }
          30%  { opacity: 1; }
          100% { transform: translateY(-10px) scale(1.15); opacity: 0; }
        }
        .petx-root .petx-sweat { display: inline-block; animation: petx-sweatf 1.2s ease-in infinite; font-size: 13px; }
        @keyframes petx-sweatf {
          0%   { transform: translateY(0); opacity: 0; }
          30%  { opacity: 1; }
          100% { transform: translateY(8px); opacity: 0; }
        }
        .petx-root.petx-state-thinking .petx-fx-thinking { display: inline-flex; top: 0; left: 10px; }
        .petx-root.petx-state-working  .petx-fx-working  { display: inline-flex; top: 4px; right: 4px; }
        .petx-root.petx-state-speaking .petx-fx-speaking { display: inline-flex; top: 0; left: 20px; }
        .petx-root.petx-state-happy     .petx-fx-happy     { display: inline-flex; top: 4px; left: 26px; }
        .petx-root.petx-state-error     .petx-fx-error     { display: inline-flex; top: 0; left: 30px; border-color: rgba(217, 84, 79, 0.3); }

        /* 确认气泡（只展示，按钮在仪表盘确认弹窗） */
        .petx-root .petx-confirm {
          display: none;
          position: absolute;
          top: -6px;
          left: 8px;
          width: 150px;
          background: rgba(255, 255, 255, 0.96);
          border: 1px solid rgba(61, 50, 46, 0.1);
          border-radius: 12px;
          padding: 8px 10px;
          box-shadow: 0 4px 14px rgba(122, 52, 31, 0.14);
        }
        .petx-root.petx-state-waiting_confirm .petx-confirm { display: block; }
        .petx-root .petx-q { font-size: 12px; font-weight: 600; margin-bottom: 4px; }
        .petx-root .petx-desc {
          font-family: var(--font-code, Consolas, monospace);
          font-size: 10px;
          color: var(--text-2, #8c7e76);
          word-break: break-all;
          max-height: 48px;
          overflow: auto;
        }

        /* 卖萌台词气泡（点小鱼弹出） */
        .petx-root .petx-cute {
          position: absolute;
          top: -8px;
          left: 6px;
          max-width: 172px;
          background: rgba(255, 255, 255, 0.97);
          border: 1px solid rgba(61, 50, 46, 0.1);
          border-radius: 14px;
          padding: 7px 12px;
          font-size: 12px;
          color: var(--text-1, #3d322e);
          box-shadow: 0 4px 14px rgba(122, 52, 31, 0.16);
          z-index: 7;
          pointer-events: none;
          white-space: nowrap;
          animation: petx-cute-pop 0.28s ease;
        }
        @keyframes petx-cute-pop {
          from { transform: scale(0.7); opacity: 0; }
          to   { transform: scale(1); opacity: 1; }
        }

        /* 隐藏 / 关闭 */
        .petx-root .petx-close {
          position: absolute;
          top: -6px;
          right: 2px;
          z-index: 61;
          display: none;
          width: 18px;
          height: 18px;
          line-height: 16px;
          text-align: center;
          border: none;
          border-radius: 50%;
          background: rgba(61, 50, 46, 0.1);
          color: var(--text-1, #3d322e);
          font-size: 12px;
          cursor: pointer;
          pointer-events: auto;
        }
        .petx-root:hover .petx-close { display: block; }
        .petx-restore {
          position: fixed;
          right: 16px;
          bottom: 14px;
          z-index: 60;
          width: 34px;
          height: 34px;
          border: none;
          border-radius: 50%;
          background: rgba(255, 255, 255, 0.92);
          box-shadow: 0 2px 10px rgba(122, 52, 31, 0.16);
          font-size: 16px;
          cursor: pointer;
        }
        .petx-restore:hover { transform: scale(1.1); }

        @media (prefers-reduced-motion: reduce) {
          .petx-root .petx-fish svg,
          .petx-root .petx-side-wrap,
          .petx-root .petx-mirror,
          .petx-root .petx-part,
          .petx-root .petx-eye,
          .petx-root .petx-lid,
          .petx-root .petx-bubble { animation: none !important; }
        }
      `}</style>
    </div>
  )
}
