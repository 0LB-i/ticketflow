import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    // Em desenvolvimento a API roda no uvicorn; em produção, na mesma origem (ADR 0010).
    proxy: { '/api': 'http://127.0.0.1:8000' },
    // Atrás do nginx (scripts/instalar-servico-dev.sh), o navegador abre o websocket na 443.
    hmr: process.env.TF_HMR_PORT ? { clientPort: Number(process.env.TF_HMR_PORT) } : undefined,
  },
  test: {
    environment: 'jsdom',
    // Um jsdom por processo, com cada arquivo ainda isolado: os testes levam um terço do tempo.
    pool: 'vmThreads',
    include: ['src/**/*.test.ts'],
  },
})
