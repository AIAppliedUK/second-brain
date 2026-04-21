import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.SECOND_BRAIN_WEB_PORT ?? '5179'),
    proxy: {
      '/api': `http://127.0.0.1:${process.env.SECOND_BRAIN_API_PORT ?? '8090'}`,
    },
  },
})
