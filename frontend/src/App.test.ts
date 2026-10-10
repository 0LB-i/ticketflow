import { afterEach, describe, expect, it, vi } from 'vitest'

import { criarRouter } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { ME_AGENTE, montar, simularApi } from '@/test/setup'

import App from './App.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('App', () => {
  it('ao sair, esquece os dados de quem estava logado', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: () => {} }))
    simularApi({
      'GET /api/v1/me': [200, ME_AGENTE],
      'GET /api/health': [200, { status: 'ok', version: '0.1.0', database: 'ok' }],
    })
    const router = criarRouter()
    const w = montar(App, { global: { plugins: [router] } })
    await router.isReady()
    await vi.waitFor(() => expect(useAuthStore().me?.id).toBe(ME_AGENTE.id))
    w.queryClient.setQueryData(['chamados'], { pages: [] })

    useAuthStore().esquecer()
    await vi.waitFor(() => expect(w.queryClient.getQueryData(['chamados'])).toBeUndefined())
  })
})
