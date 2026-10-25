import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// Dev-proxy для `npm run dev` с хоста: /api/* → gateway, префикс /api срезается,
// как в nginx-прокси контейнера.
const gatewayPort = process.env.GATEWAY_PORT ?? '8080'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: `http://localhost:${gatewayPort}`,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
  },
})
