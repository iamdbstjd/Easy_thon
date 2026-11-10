import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 백엔드(FastAPI)는 로컬 8000번 포트에서 돈다. 개발 서버와 preview 모두 /api를 넘긴다.
// 다른 주소의 백엔드를 쓰려면: API_TARGET=http://127.0.0.1:8011 npm run dev
const proxy = {
  '/api': process.env.API_TARGET ?? 'http://127.0.0.1:8000',
}

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
})
