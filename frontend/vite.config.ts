import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  // Shown on the dashboard (src/buildInfo.ts) to tell deploys apart.
  define: {
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
  },
  plugins: [
    react(),
    VitePWA({
      // 'prompt' so src/pwaUpdate.ts decides *when* a waiting update takes
      // over (it reloads the page), instead of a reload at an arbitrary
      // moment mid-workout.
      registerType: 'prompt',
      // Data (dashboard/session state) must always be fresh — only the
      // built app shell (JS/CSS/HTML/icons) is precached, /api/* is left
      // untouched by the service worker (NetworkOnly by default).
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,jpg,svg}'],
        // Page loads go to the network first, so opening the app after a
        // deploy always gets the new index.html (and through it the new
        // hashed JS/CSS) instead of the old precached shell, which would
        // otherwise run until src/pwaUpdate.ts gets to swap workers. The
        // cached page is only used offline, or when the network is slow.
        navigateFallback: null,
        runtimeCaching: [
          {
            urlPattern: ({ request }) => request.mode === 'navigate',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'pages',
              networkTimeoutSeconds: 4,
              expiration: { maxEntries: 20 },
            },
          },
        ],
      },
      manifest: {
        name: 'AI Fitness Coach',
        short_name: 'Fitness Coach',
        description: 'Your weekly workout plan, guided set by set.',
        theme_color: '#f6f1e7',
        background_color: '#f6f1e7',
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
