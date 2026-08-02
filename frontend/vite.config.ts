import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      // Data (dashboard/session state) must always be fresh — only the
      // built app shell (JS/CSS/HTML/icons) is precached, /api/* is left
      // untouched by the service worker (NetworkOnly by default).
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,jpg,svg}'],
      },
      manifest: {
        name: 'AI Fitness Coach',
        short_name: 'Fitness Coach',
        description: 'Your weekly workout plan, guided set by set.',
        theme_color: '#0071e3',
        background_color: '#f5f5f7',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/icons/icon-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      '/api': 'http://localhost:8001',
    },
  },
})
