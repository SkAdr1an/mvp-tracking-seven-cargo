import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backendProxy = {
  target: 'http://localhost:8000',
  changeOrigin: true,
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': backendProxy,
      '/health': backendProxy,
      '/integrations': backendProxy,
      '/fleet': backendProxy,
      '/routes': backendProxy,
      '/trafegus': backendProxy,
      '/operations': backendProxy,
      '/traffic': backendProxy,
      '/operational-sites': backendProxy,
      '/angellira': backendProxy,
      '/tracking': {
        ...backendProxy,
        ws: true,
      },
    },
  },
})
