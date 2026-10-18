import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// No serviço de desenvolvimento (scripts/instalar-servico-dev.sh), o uvicorn fica na 8001.
const uvicorn = process.env.TF_HMR_PORT ? 'http://127.0.0.1:8001' : 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    // Em desenvolvimento a API roda no uvicorn; em produção, na mesma origem (ADR 0010).
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      // Telas que já migraram para o servidor e os arquivos delas (ADR 0011): a raiz, o login e
      // as telas de senha, o idioma, tudo de /chamados e /clientes, e clientes, usuários, grupos e setores da administração.
      '^/(static/|convite/|redefinir-senha/|chamados/|clientes/|admin/(clientes|usuarios|grupos|setores)(/|\\?|$)|(chamados|login|sair|esqueci-senha|trocar-senha|idioma)?(\\?|$))':
        uvicorn,
    },
    // Atrás do nginx (scripts/instalar-servico-dev.sh), o navegador abre o websocket na 443.
    hmr: process.env.TF_HMR_PORT ? { clientPort: Number(process.env.TF_HMR_PORT) } : undefined,
  },
  test: {
    environment: 'jsdom',
    // Um jsdom por processo, com cada arquivo ainda isolado: os testes levam um terço do tempo.
    pool: 'vmThreads',
    // afterEach na ordem de registro: o do test/setup.ts (desmonta) antes do de cada arquivo
    // (limpa o document.body).
    sequence: { hooks: 'list' },
    include: ['src/**/*.test.ts'],
  },
})
