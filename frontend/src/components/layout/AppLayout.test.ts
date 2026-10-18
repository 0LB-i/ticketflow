import { afterEach, describe, expect, it, vi } from 'vitest'

import { criarRouter } from '@/router'
import { ME_AGENTE, montar, simularApi } from '@/test/setup'

import AppLayout from './AppLayout.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const ME = { ...ME_AGENTE, display_name: 'Ana', permissions: ['ticket.create'] }

describe('busca no cabeçalho', () => {
  it('número abre o chamado; texto vai para a lista', async () => {
    simularApi({ 'GET /api/v1/me': [200, ME] })
    // O menu de tema consulta o modo do sistema, que o jsdom não tem.
    vi.stubGlobal('matchMedia', () => ({
      matches: false,
      addEventListener: () => {},
      removeEventListener: () => {},
    }))
    const router = criarRouter()
    const w = montar(AppLayout, { global: { plugins: [router] } })
    await router.push('/chamados')
    // Confere os pedidos de navegação: carregar as telas (o chamado tem o editor) é lento no jsdom.
    const navegar = vi.spyOn(router, 'push').mockResolvedValue(undefined)
    const campo = w.get('input[type=search]')

    await campo.setValue('#1234')
    await w.get('form[role=search]').trigger('submit')
    expect(navegar).toHaveBeenLastCalledWith('/chamados/1234')

    await campo.setValue('impressora')
    await w.get('form[role=search]').trigger('submit')
    expect(navegar).toHaveBeenLastCalledWith({
      name: 'chamados',
      query: { aba: 'todos', q: 'impressora' },
    })
  })
})
