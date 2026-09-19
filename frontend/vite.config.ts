/**
 * Vite 构建配置
 * ==============
 * 小白理解:前端开发服务器(5173 端口)在运行时会把所有 /api 开头的请求
 * "转接"给后端(8000 端口)。就像前台总机,访客不用知道后端具体在哪。
 */
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 所有 /api 请求转给后端服务
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
