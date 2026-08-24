/**
 * 外观个性化（P3：自定义背景图 + 半透明蒙版 + 模糊）。
 *
 * - 背景图以 dataURL 存 localStorage（canvas 压缩到 ≤1920 宽 / JPEG 0.82），
 *   防止撑爆 5MB 限额；
 * - 渲染靠 CSS 变量（--app-bg-image / --app-bg-mask / --app-bg-blur），
 *   index.css 中 .app-bg 层消费，未设置时一切退回纯色渐变。
 */

export interface Appearance {
  /** dataURL；null = 未自定义 */
  bgImage: string | null
  /** 蒙版不透明度 0~1（作用于暖白蒙版层） */
  maskOpacity: number
  /** 背景模糊半径 px */
  blur: number
}

const KEY = 'miniagent_appearance_v2'
const LEGACY_KEY = 'miniagent_appearance_v1'
export const MAX_IMAGE_BYTES = 2.2 * 1024 * 1024

export const DEFAULT_APPEARANCE: Appearance = {
  bgImage: null,
  maskOpacity: 0.32,
  blur: 0,
}

function normalize(d: Partial<Appearance>): Appearance {
  return {
    bgImage: typeof d.bgImage === 'string' ? d.bgImage : null,
    maskOpacity: clamp01(typeof d.maskOpacity === 'number' ? d.maskOpacity : 0.32),
    blur: typeof d.blur === 'number' ? Math.min(24, Math.max(0, d.blur)) : 0,
  }
}

export function loadAppearance(): Appearance {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) return normalize(JSON.parse(raw))
    // v1 迁移：保留图片与模糊；蒙版若为旧默认（0.82 / 0.45，用户从未动过滑杆）
    // 则降到新默认 0.32 —— 旧默认把壁纸糊得太死，是「看不到背景图」的主因之一。
    const legacy = localStorage.getItem(LEGACY_KEY)
    if (legacy) {
      const d = JSON.parse(legacy)
      const migrated = normalize({
        ...d,
        maskOpacity: d.maskOpacity === 0.82 || d.maskOpacity === 0.45 ? 0.32 : d.maskOpacity,
      })
      saveAppearance(migrated)
      localStorage.removeItem(LEGACY_KEY)
      return migrated
    }
    return { ...DEFAULT_APPEARANCE }
  } catch {
    return { ...DEFAULT_APPEARANCE }
  }
}

export function saveAppearance(a: Appearance) {
  try {
    localStorage.setItem(KEY, JSON.stringify(a))
  } catch {
    /* 超限时静默失败（调用方在导入时已做压缩与体积校验） */
  }
}

/** 把外观写进文档级 CSS 变量（App 启动 / 设置变更时调用）。 */
export function applyAppearance(a: Appearance) {
  const root = document.documentElement
  if (a.bgImage) {
    root.style.setProperty('--app-bg-image', `url("${a.bgImage}")`)
    root.classList.add('has-custom-bg')
  } else {
    root.style.removeProperty('--app-bg-image')
    root.classList.remove('has-custom-bg')
  }
  // 蒙版：暖白底色按不透明度混合，保证正文 #1e293b 可读
  root.style.setProperty('--app-bg-mask', `rgba(251, 247, 244, ${a.maskOpacity})`)
  root.style.setProperty('--app-bg-blur', `${a.blur}px`)
}

/**
 * 导入本地图片：File → 压缩 dataURL。
 * 宽度超 1920 或体积超限时用 canvas 等比缩放重绘。
 */
export async function importImageFile(file: File): Promise<string> {
  const rawUrl = await new Promise<string>((resolve, reject) => {
    const fr = new FileReader()
    fr.onload = () => resolve(String(fr.result))
    fr.onerror = () => reject(new Error('读取文件失败'))
    fr.readAsDataURL(file)
  })

  // 体积可接受且本身不大（罕见：小图直接用）
  if (rawUrl.length <= MAX_IMAGE_BYTES) {
    const img = await loadImage(rawUrl)
    if (img.naturalWidth <= 1920) return rawUrl
  }

  const img = await loadImage(rawUrl)
  const scale = Math.min(1, 1920 / img.naturalWidth)
  const w = Math.max(1, Math.round(img.naturalWidth * scale))
  const h = Math.max(1, Math.round(img.naturalHeight * scale))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return rawUrl
  ctx.drawImage(img, 0, 0, w, h)
  let out = canvas.toDataURL('image/jpeg', 0.82)
  // 仍超限 → 再压一档质量
  if (out.length > MAX_IMAGE_BYTES) {
    out = canvas.toDataURL('image/jpeg', 0.6)
  }
  if (out.length > MAX_IMAGE_BYTES) {
    throw new Error('图片过大，请换一张（压缩后仍超过 2MB）')
  }
  return out
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('图片解析失败'))
    img.src = src
  })
}

function clamp01(n: number) {
  return Math.min(1, Math.max(0, n))
}
