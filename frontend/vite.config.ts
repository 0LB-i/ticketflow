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
    // TF_API: o serviço de desenvolvimento (scripts/instalar-servico-dev.sh) usa outra porta.
    // xfwd: o IP de quem acessa chega à API (limite de tentativas de login por IP).
    proxy: { '/api': { target: process.env.TF_API ?? 'http://127.0.0.1:8000', xfwd: true } },
  },
  test: {
    environment: 'jsdom',
    // Um jsdom por processo, com cada arquivo ainda isolado: os testes levam um terço do tempo.
    pool: 'vmThreads',
    include: ['src/**/*.test.ts'],
  },
})
