import { defineConfig } from 'vite'
import preact from '@preact/preset-vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    preact(),
    VitePWA({
      registerType: 'autoUpdate',   // 新版本部署後自動更新，不用手動清快取
      includeAssets: ['apple-touch-icon.png'],
      manifest: {
        name: '幣勢監控',
        short_name: '幣勢監控',
        description: '短線交易監控：新聞面/技術面/籌碼面',
        lang: 'zh-Hant',
        display: 'standalone',
        orientation: 'portrait',
        theme_color: '#0d1117',
        background_color: '#0d1117',
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          { src: 'pwa-maskable-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // 只快取靜態資源；行情/API 永遠走網路，避免看到舊數據
        globPatterns: ['**/*.{js,css,html,png}'],
        navigateFallback: 'index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/tasks\//, /^\/healthz/],
      },
    }),
  ],
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
