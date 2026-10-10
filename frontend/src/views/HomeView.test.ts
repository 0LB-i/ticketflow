import { afterEach, describe, expect, it, vi } from 'vitest'

import { montar } from '@/test/setup'

import HomeView from './HomeView.vue'

function respostaDaApi(status: number, corpo: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify(corpo), {
          status,
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  )
}

describe('HomeView', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('mostra o estado do sistema vindo do /api/health', async () => {
    respostaDaApi(200, { status: 'ok', version: '0.1.0', database: 'PostgreSQL 17.11' })
    const w = montar(HomeView)
    await vi.waitFor(() => expect(w.text()).toContain('Funcionando'))
    expect(w.text()).toContain('PostgreSQL 17.11')
  })

  it('avisa quando o servidor não responde', async () => {
    respostaDaApi(503, { title: 'Serviço indisponível', status: 503 })
    const w = montar(HomeView)
    await vi.waitFor(() => expect(w.text()).toContain('Não foi possível consultar o servidor'))
  })
})
