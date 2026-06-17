import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// El build se sirve desde FastAPI bajo /static, y la SPA vive en /.
// En desarrollo, Vite proxya /api al backend de FastAPI.
export default defineConfig({
  plugins: [react()],
  base: '/static/',
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: '../app/static',
    emptyOutDir: true,
  },
})
