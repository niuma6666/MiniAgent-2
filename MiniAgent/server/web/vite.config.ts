import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// dev：5173 起 dev server，/ws 的 WebSocket 代理到后端 8000（同源协议，前端代码无需区分模式）
// prod：vite build 产物在 server/web/dist，由 FastAPI（server/app.py）静态托管
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
    // 忽略编辑器原子写入产生的临时文件（.tmpdir/.tmp/~xxx.TMP），
    // 否则 chokidar 在 Windows 上 watch 它们会 EBUSY 崩溃
    watch: {
      ignored: [/\.tmp/i, /~$/, /(^|[\\/])\../],
    },
  },
  build: {
    outDir: 'dist',
  },
})
