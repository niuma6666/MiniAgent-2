import { create } from 'zustand'

/**
 * UI 布局状态（P3 改版）：
 * - mode：三档布局预设（focus 专注 / debug 调试 / present 演示），存 localStorage；
 * - sidebarOpen / toolsOpen：侧栏与工具面板的独立折叠，切预设时联动归位。
 */

export type UIMode = 'focus' | 'debug' | 'present'

export interface UIState {
  mode: UIMode
  sidebarOpen: boolean
  toolsOpen: boolean
  settingsOpen: boolean

  setMode: (m: UIMode) => void
  toggleSidebar: () => void
  toggleTools: () => void
  setSettingsOpen: (open: boolean) => void
}

const KEY = 'miniagent_ui_v1'

function loadMode(): UIMode {
  try {
    const m = JSON.parse(localStorage.getItem(KEY) || '').mode
    return m === 'focus' || m === 'present' ? m : 'debug'
  } catch {
    return 'debug'
  }
}

/** 各预设下侧栏/工具面板的默认开合 */
const PRESET: Record<UIMode, { sidebar: boolean; tools: boolean }> = {
  focus: { sidebar: false, tools: false },
  debug: { sidebar: true, tools: true },
  present: { sidebar: false, tools: false },
}

export const useUIStore = create<UIState>((set, get) => ({
  mode: loadMode(),
  sidebarOpen: PRESET[loadMode()].sidebar,
  toolsOpen: PRESET[loadMode()].tools,
  settingsOpen: false,

  setMode(m) {
    try {
      localStorage.setItem(KEY, JSON.stringify({ mode: m }))
    } catch {
      /* 静默 */
    }
    set({ mode: m, sidebarOpen: PRESET[m].sidebar, toolsOpen: PRESET[m].tools })
  },
  toggleSidebar() {
    set({ sidebarOpen: !get().sidebarOpen })
  },
  toggleTools() {
    set({ toolsOpen: !get().toolsOpen })
  },
  setSettingsOpen(open) {
    set({ settingsOpen: open })
  },
}))

export const MODE_LABEL: Record<UIMode, string> = {
  focus: '专注',
  debug: '调试',
  present: '演示',
}
