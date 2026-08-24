import { useEffect, useRef, useState } from 'react'
import {
  loadAppearance,
  saveAppearance,
  applyAppearance,
  importImageFile,
  type Appearance,
} from '../lib/appearance'
import { useUIStore } from '../uiStore'

/**
 * 外观设置弹窗：自定义背景图（本地导入 + 压缩）、
 * 半透明蒙版浓度滑杆、背景模糊滑杆。
 */
export default function SettingsModal() {
  const settingsOpen = useUIStore((s) => s.settingsOpen)
  const setSettingsOpen = useUIStore((s) => s.setSettingsOpen)

  // 弹窗打开时重新读 localStorage（外部可能变更）
  const [app, setApp] = useState<Appearance>(() => loadAppearance())
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (settingsOpen) {
      setApp(loadAppearance())
      setError('')
    }
  }, [settingsOpen])

  if (!settingsOpen) return null

  function update(patch: Partial<Appearance>) {
    const next = { ...app, ...patch }
    setApp(next)
    saveAppearance(next)
    applyAppearance(next)
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const dataUrl = await importImageFile(file)
      update({ bgImage: dataUrl })
    } catch (err) {
      setError(err instanceof Error ? err.message : '导入失败')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="confirm-overlay" onClick={() => setSettingsOpen(false)}>
      <div className="confirm-box settings-box" onClick={(e) => e.stopPropagation()}>
        <div className="c-title">🎨 外观设置</div>

        <div className="settings-section">
          <div className="settings-label">背景图片</div>
          <div className="settings-row">
            <button className="btn small" onClick={() => fileRef.current?.click()} disabled={busy}>
              {busy ? '处理中…' : app.bgImage ? '更换图片' : '选择本地图片'}
            </button>
            {app.bgImage && (
              <button className="btn small danger-flat" onClick={() => update({ bgImage: null })}>
                移除
              </button>
            )}
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              style={{ display: 'none' }}
              onChange={onFile}
            />
          </div>
          {app.bgImage && (
            <div
              className="settings-preview"
              style={{ backgroundImage: `url("${app.bgImage}")` }}
            />
          )}
          <div className="prop-hint">自动压缩到 1920 宽 / JPEG，不会撑爆本地存储。</div>
        </div>

        <div className="settings-section">
          <div className="settings-label">
            蒙版浓度 <span className="muted">{Math.round(app.maskOpacity * 100)}%</span>
          </div>
          <input
            type="range"
            min={40}
            max={97}
            value={Math.round(app.maskOpacity * 100)}
            onChange={(e) => update({ maskOpacity: Number(e.target.value) / 100 })}
          />
          <div className="prop-hint">越高文字越清晰，越低壁纸越明显（建议 40%~60%，可兼顾两者）。</div>
        </div>

        <div className="settings-section">
          <div className="settings-label">
            背景模糊 <span className="muted">{app.blur}px</span>
          </div>
          <input
            type="range"
            min={0}
            max={20}
            value={app.blur}
            onChange={(e) => update({ blur: Number(e.target.value) })}
          />
        </div>

        {error && <div className="error-line">❌ {error}</div>}

        <div className="c-actions">
          <button className="btn primary" onClick={() => setSettingsOpen(false)}>
            完成
          </button>
        </div>
      </div>
    </div>
  )
}
