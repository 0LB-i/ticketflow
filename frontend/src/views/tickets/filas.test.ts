import { afterEach, describe, expect, it, vi } from 'vitest'

import AppLayout from '@/components/layout/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import { criarRouter } from '@/router'
import { escolher, ME_AGENTE, montar, simularApi } from '@/test/setup'

import TicketsView from './TicketsView.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const TI = '00000000-0000-0000-0000-0000000000a1'
const ME = {
  ...ME_AGENTE,
  display_name: 'Ana',
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
  assignee: { id: ME.id, display_name: 'Ana' },
  started_at: '2026-10-10T11:30:00Z',
  created_at: '2026-10-10T12:00:00Z',
  updated_at: '2026-10-10T12:00:00Z',
  has_news: true,
  time_spent_minutes: 135,
}
const CONTAGENS = { mine: 1, news: 1, waiting: 0, watching: 2 }

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
    expect(w.findAll('[role=tab]').map((a) => a.text())).toEqual([
      'Meus 1',
      'Com novidades 1',
      'Aguardando',
      'Acompanhando 2',
      'Todos',
    ])
    expect(w.find('[aria-label="Tarefa nova de outra pessoa"]').exists()).toBe(true)
    expect(w.text()).toContain('Padaria Pão Quente')
  })

  it('cada linha tem o total de horas e o lápis que abre o chamado; quem não supervisiona não seleciona', async () => {
    api()
    const router = criarRouter()
    const w = montar(TicketsView, { global: { plugins: [router] } })
    await router.push('/chamados')
    await vi.waitFor(() => expect(w.text()).toContain('Impressora parada'))
    const editar = w.get('a[aria-label="Editar o chamado #1000"]')
    expect(editar.attributes('href')).toBe('/chamados/1000')
    const celulas = w.findAll('tbody tr')[0]!.findAll('td')
    expect(celulas.at(-2)!.text()).toBe('2h15') // total de horas, ao lado da última movimentação
    expect(w.findAll('th').map((th) => th.text())).toContain('Total de horas')
    expect(w.findAll('tbody tr')[0]!.findAll('td').at(-1)!.find('a').exists()).toBe(true) // último
    expect(w.find('input[type=checkbox]').exists()).toBe(false)
  })

  it('o supervisor seleciona vários chamados e muda o status deles', async () => {
    const OUTRO = { ...ITEM, id: 'd2', number: 1001, title: 'Sem rede' }
    const feitas = api({
      'GET /api/v1/me': [200, { ...ME, teams: [{ id: TI, name: 'TI', role: 'supervisor' }] }],
      'GET /api/v1/tickets': [200, { items: [ITEM, OUTRO], next_cursor: null }],
      'GET /api/v1/statuses': [
        200,
        {
          items: [
            { id: 1, name: 'Pendente', kind: 'open' },
            { id: 5, name: 'Concluído', kind: 'closed' },
          ],
        },
      ],
      'POST /api/v1/tickets/bulk/status': [
        200,
        { updated: [1000], failed: [{ number: 1001, detail: 'Você não pode fazer isso.' }] },
      ],
    })
    const router = criarRouter()
    const w = montar(TicketsView, { global: { plugins: [router] } })
    await router.push('/chamados')
    await vi.waitFor(() => expect(w.text()).toContain('Sem rede'))
    expect(w.text()).not.toContain('Mudar status') // a barra só aparece com seleção

    await w.get('th input[type=checkbox]').setValue(true)
    await vi.waitFor(() => expect(w.text()).toContain('Selecionados: 2'))
    // Janela flutuante, presa no pé da tela
    expect(w.get('[role=region][aria-label="Mudar status"]').classes()).toEqual(
      expect.arrayContaining(['fixed', 'bottom-4']),
    )
    await escolher('Novo status', 'Concluído')
    await w
      .findAll('button')
      .find((b) => b.text() === 'Mudar status')!
      .trigger('click')
    await vi.waitFor(() =>
      expect(feitas.find((r) => r.caminho.endsWith('/bulk/status'))?.corpo).toEqual({
        numbers: [1000, 1001],
        status_id: 5,
      }),
    )
    // O que não mudou continua selecionado, e o motivo aparece
    await vi.waitFor(() => expect(w.text()).toContain('Selecionados: 1'))
    expect(useToast().avisos.value.map((a) => a.title)).toEqual(
      expect.arrayContaining([
        'Chamados alterados: 1',
        'Não mudaram: #1001 (Você não pode fazer isso.)',
      ]),
    )
  })

  it('a aba e os filtros vão para a URL e para a API', async () => {
    const feitas = api()
    const router = criarRouter()
    const w = montar(TicketsView, { global: { plugins: [router] } })
    await router.push(`/chamados?aba=todos&status=waiting&responsavel=eu&grupo=${TI}&q=toner`)

    await vi.waitFor(() => expect(w.text()).toContain('Resultados da busca por “toner”'))
    const q = await vi.waitFor(() => {
      const busca = listas(feitas).find((r) => r.get('q') === 'toner')
      expect(busca).toBeTruthy()
      return busca!
    })
    expect(Object.fromEntries(q)).toEqual({
      view: 'all',
      status: 'waiting',
      assignee: 'me',
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
    await vi.waitFor(() => expect(w.text()).toContain('Nenhum chamado com você.'))
    expect(w.text()).not.toContain('Pegar o próximo')
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
