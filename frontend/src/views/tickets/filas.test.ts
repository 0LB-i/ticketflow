import { afterEach, describe, expect, it, vi } from 'vitest'

import AppLayout from '@/components/layout/AppLayout.vue'
import { criarRouter } from '@/router'
import { ME_AGENTE, montar, simularApi } from '@/test/setup'

import TicketsView from './TicketsView.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const TI = '00000000-0000-0000-0000-0000000000a1'
const ME = {
  ...ME_AGENTE,
  full_name: 'Ana',
  teams: [{ id: TI, name: 'TI', role: 'member' as const }],
  permissions: ['ticket.create', 'ticket.assign_self'],
}
const ITEM = {
  id: '00000000-0000-0000-0000-0000000000d1',
  number: 1000,
  title: 'Impressora parada',
  type: 'incident',
  status: { id: 1, name: 'Pendente', kind: 'open' },
  team: { id: TI, name: 'TI' },
  category: null,
  department: null,
  client: { id: 'p', name: 'Padaria Pão Quente' },
  beneficiary_name: null,
  assignee: { id: ME.id, full_name: 'Ana' },
  started_at: '2026-10-10T11:30:00Z',
  created_at: '2026-10-10T12:00:00Z',
  updated_at: '2026-10-10T12:00:00Z',
  has_news: true,
}
const CONTAGENS = { unassigned: 7, mine: 1, news: 1, waiting: 0, watching: 2 }

function api(extras: Record<string, [number, unknown?]> = {}) {
  return simularApi({
    'GET /api/v1/me': [200, ME],
    'GET /api/v1/teams': [200, { items: [] }],
    'GET /api/v1/tickets': [200, { items: [ITEM], next_cursor: null }],
    'GET /api/v1/tickets/counts': [200, CONTAGENS],
    ...extras,
  })
}
const listas = (feitas: ReturnType<typeof simularApi>) =>
  feitas.filter((r) => r.caminho === '/api/v1/tickets').map((r) => r.query)

describe('TicketsView', () => {
  it('abre em Meus, com os contadores e o aviso de novidade', async () => {
    const feitas = api()
    const router = criarRouter()
    const w = montar(TicketsView, { global: { plugins: [router] } })
    await router.push('/chamados')

    await vi.waitFor(() => expect(w.text()).toContain('Impressora parada'))
    expect(listas(feitas).at(-1)!.get('view')).toBe('mine')
    expect(w.get('[role=tab][data-state=active]').text()).toContain('Meus')
    expect(w.findAll('[role=tab]').map((a) => a.text())).toContain('Não atribuídos 7')
    expect(w.find('[aria-label="Tarefa nova de outra pessoa"]').exists()).toBe(true)
    expect(w.text()).toContain('Padaria Pão Quente')
  })

  it('a aba e os filtros vão para a URL e para a API', async () => {
    const feitas = api()
    const router = criarRouter()
    const w = montar(TicketsView, { global: { plugins: [router] } })
    await router.push(`/chamados?aba=todos&status=waiting&responsavel=ninguem&grupo=${TI}&q=toner`)

    await vi.waitFor(() => expect(w.text()).toContain('Resultados da busca por “toner”'))
    const q = await vi.waitFor(() => {
      const busca = listas(feitas).find((r) => r.get('q') === 'toner')
      expect(busca).toBeTruthy()
      return busca!
    })
    expect(Object.fromEntries(q)).toEqual({
      view: 'all',
      status: 'waiting',
      assignee: 'none',
      team: TI,
      q: 'toner',
    })

    // Outra aba: status e responsável deixam de valer
    await w
      .findAll('[role=tab]')
      .find((a) => a.text().startsWith('Aguardando'))!
      .trigger('mousedown', { button: 0 })
    await vi.waitFor(() => expect(router.currentRoute.value.query.aba).toBe('aguardando'))
    expect(router.currentRoute.value.query).toEqual({
      aba: 'aguardando',
      grupo: TI,
      q: 'toner',
    })
    await vi.waitFor(() => expect(listas(feitas).at(-1)!.get('view')).toBe('waiting'))

    await w
      .findAll('button')
      .find((b) => b.text() === 'Limpar a busca')!
      .trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.query.q).toBeUndefined())

    await w
      .findAll('[role=tab]')
      .find((a) => a.text().startsWith('Todos'))!
      .trigger('mousedown', { button: 0 })
    await vi.waitFor(() =>
      expect(router.currentRoute.value.query).toEqual({ aba: 'todos', grupo: TI }),
    )
  })

  it('a lista vazia explica o que fazer', async () => {
    api({ 'GET /api/v1/tickets': [200, { items: [], next_cursor: null }] })
    const router = criarRouter()
    const w = montar(TicketsView, { global: { plugins: [router] } })
    await router.push('/chamados')
    await vi.waitFor(() => expect(w.text()).toContain('Que tal pegar o próximo da fila?'))
  })

  it('pegar o próximo assume e abre o chamado', async () => {
    const feitas = api({
      'POST /api/v1/tickets/next': [200, { ...ITEM, number: 1005, title: 'VPN' }],
    })
    const router = criarRouter()
    const w = montar(TicketsView, { global: { plugins: [router] } })
    await router.push(`/chamados?grupo=${TI}`)
    await vi.waitFor(() => expect(w.text()).toContain('Pegar o próximo'))
    // Confere o pedido de navegação: carregar a tela do chamado (com o editor) é lento no jsdom.
    const navegar = vi.spyOn(router, 'push').mockResolvedValue(undefined)

    await w
      .findAll('button')
      .find((b) => b.text() === 'Pegar o próximo')!
      .trigger('click')
    await vi.waitFor(() => expect(navegar).toHaveBeenCalledWith('/chamados/1005'))
    expect(feitas.find((r) => r.metodo === 'POST')!.corpo).toEqual({ team_id: TI })
  })
})

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
