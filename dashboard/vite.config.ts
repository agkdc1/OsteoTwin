import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8200',
      '/auth': 'http://localhost:8200',
      '/admin': 'http://localhost:8200',
      '/health': 'http://localhost:8200',
      '/stl-proxy': 'http://localhost:8200',
      '/sim-api': {
        target: 'http://localhost:8300',
        rewrite: (path) => path.replace(/^\/sim-api/, '/api'),
      },
    },
  },
})
