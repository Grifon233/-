import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // The bundled @phosphor-icons/react index.cjs.js is empty in this
  // version (2.1.10) — the real exports live in dist/index.es.js
  // and per-icon files under dist/csr/*.es.js. Force Vite to pick
  // the ESM build via optimizeDeps include so the named imports
  // (UserCircle, GenderMale, etc.) actually resolve at dev time.
  optimizeDeps: {
    include: ['@phosphor-icons/react'],
    esbuildOptions: {
      mainFields: ['module', 'jsnext:main', 'jsnext'],
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5177,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
