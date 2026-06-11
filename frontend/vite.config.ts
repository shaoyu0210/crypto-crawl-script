import { defineConfig } from 'vite'
import preact from '@preact/preset-vite'

export default defineConfig({
  plugins: [preact()],
  build: {
    outDir: '../backend/static',   // FastAPI 直接 serve 此目錄
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',   // 本機開發：Vite dev server 轉發後端
    },
  },
})
