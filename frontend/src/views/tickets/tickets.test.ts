import { afterEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import { criarRouter } from '@/router'
import { ME_AGENTE, montar, simularApi } from '@/test/setup'

import NewTicketView from './NewTicketView.vue'
import TicketView from './TicketView.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const TI = '00000000-0000-0000-0000-0000000000a1'
const ANA = ME_AGENTE.id
const BIA = '00000000-0000-0000-0000-0000000000b2'
const IMPRESSAO = '00000000-0000-0000-0000-0000000000c1'
const ME = {
  ...ME_AGENTE,
  full_name: 'Ana',
  teams: [{ id: TI, name: 'TI', role: 'member' as const }],
  permissions: ['ticket.create'],
}
const GRUPOS = {
  items: [
    {
      id: TI,
      name: 'TI',
      description: null,
      notify_on_new: 'queue_only',
      is_active: true,
      members: [
        { user_id: ANA, full_name: 'Ana', email: 'ana@x.com', role: 'member', is_active: true },
        { user_id: BIA, full_name: 'Bia', email: 'bia@x.com', role: 'member', is_active: true },
      ],
    },
  ],
}
const CATEGORIAS = {
  items: [
    {
      id: IMPRESSAO,
      name: 'Impressão',
      description: null,
      parent_id: null,
      default_team_id: TI,
      default_type: 'incident',
      is_confidential: false,
      is_active: true,
    },
  ],
}

/** Marca a opção (radio) cujo rótulo contém o texto. */
function marcar(w: ReturnType<typeof montar>, texto: string) {
  return w
    .findAll('label')
    .find((l) => l.text().includes(texto))!
    .get('input')
    .setValue()
}

/** Escolhe uma opção de um Select (Reka UI) pelo teclado, como um usuário. */
async function escolher(rotulo: string, opcao: string) {
  const label = [...document.querySelectorAll('label')].find((l) => l.textContent?.includes(rotulo))
  const trigger = document.getElementById(label!.htmlFor)!
  trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  const item = await vi.waitFor(() => {
    const encontrado = [...document.querySelectorAll('[role=option]')].find(
      (o) => o.textContent?.trim() === opcao,
    )
    expect(encontrado).toBeTruthy()
    return encontrado as HTMLElement
  })
  item.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await vi.waitFor(() => expect(document.querySelector('[role=listbox]')).toBeNull())
}

describe('NewTicketView', () => {
  it('registra com o grupo, a categoria, a urgência e o responsável escolhidos', async () => {
    const feitas = simularApi({
      'GET /api/v1/me': [200, ME],
      'GET /api/v1/teams': [200, GRUPOS],
      'GET /api/v1/categories': [200, CATEGORIAS],
      'GET /api/v1/departments': [200, { items: [] }],
      'POST /api/v1/tickets': [201, { number: 1000, title: 'Impressora parada' }],
    })
    const router = criarRouter()
    const w = montar(NewTicketView, { global: { plugins: [router] } })
    await router.push('/chamados/novo')

    await vi.waitFor(() => expect(w.text()).toContain('Categoria'))
    await escolher('Categoria', 'Impressão')
    await w.get('input[type=text]').setValue('Impressora parada')
    await marcar(w, 'Agora')
    await marcar(w, 'Deixar na fila')
    await w.get('form').trigger('submit')

    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/chamados/1000'))
    expect(feitas.find((r) => r.metodo === 'POST')!.corpo).toEqual({
      title: 'Impressora parada',
      description: '',
      team_id: TI,
      category_id: IMPRESSAO,
      department_id: null,
      beneficiary_name: null,
      urgency: 3,
      impact: 1,
      assignee: null,
      watcher_ids: [],
      mention_ids: [],
    })
  })

  it('não envia sem título e categoria', async () => {
    // O router faz a navegação inicial ao ser instalado, e o guard carrega o /me.
    const feitas = simularApi({
      'GET /api/v1/me': [200, ME],
      'GET /api/v1/teams': [200, GRUPOS],
      'GET /api/v1/categories': [200, CATEGORIAS],
      'GET /api/v1/departments': [200, { items: [] }],
    })
    const w = montar(NewTicketView, { global: { plugins: [criarRouter()] } })
    await vi.waitFor(() => expect(w.find('form').exists()).toBe(true))
    await w.get('form').trigger('submit')
    expect(w.text()).toContain('Escolha a categoria.')
    expect(w.text()).toContain('Informe um título com pelo menos 3 letras.')
    expect(feitas.some((r) => r.metodo === 'POST')).toBe(false)
  })
})

const CHAMADO = {
  id: '00000000-0000-0000-0000-0000000000d1',
  number: 1000,
  title: 'Impressora parada',
  type: 'incident',
  status: { id: 1, name: 'Pendente', kind: 'open' },
  priority: 3,
  team: { id: TI, name: 'TI' },
  category: { id: IMPRESSAO, name: 'Impressão', path: 'Impressão' },
  department: null,
  beneficiary_name: 'João Silva',
  assignee: null,
  created_at: '2026-10-10T12:00:00Z',
  updated_at: '2026-10-10T12:00:00Z',
  description: 'Aparece **offline**.',
  impact: 2,
  urgency: 3,
  priority_overridden: false,
  created_by: { id: BIA, full_name: 'Bia' },
  resolution_code: null,
  reopened_count: 0,
  closed_at: null,
  watchers: [],
  allowed_actions: ['assign_self', 'comment', 'edit', 'transfer', 'watch_self'],
}
const EVENTOS = {
  items: [
    {
      id: 1,
      type: 'ticket.created',
      actor: { id: BIA, full_name: 'Bia' },
      payload: {},
      created_at: '2026-10-10T12:00:00Z',
    },
    {
      id: 2,
      type: 'ticket.transferred',
      actor: { id: BIA, full_name: 'Bia' },
      payload: { from: { id: 'x', name: 'Infra' }, to: { id: TI, name: 'TI' } },
      created_at: '2026-10-10T12:05:00Z',
    },
  ],
}

describe('TicketView', () => {
  it('mostra o chamado, a linha do tempo e só as ações permitidas', async () => {
    const feitas = simularApi({
      'GET /api/v1/tickets/1000': [200, CHAMADO],
      'GET /api/v1/tickets/1000/comments': [200, { items: [] }],
      'GET /api/v1/tickets/1000/events': [200, EVENTOS],
      'GET /api/v1/teams': [200, GRUPOS],
      'POST /api/v1/tickets/1000/assign': [
        200,
        { ...CHAMADO, assignee: { id: ANA, full_name: 'Ana' } },
      ],
    })
    const w = montar(TicketView, { props: { numero: '1000' } })
    useAuthStore().me = ME

    await vi.waitFor(() => expect(w.text()).toContain('Impressora parada'))
    expect(w.find('strong').text()).toBe('offline')
    expect(w.text()).toContain('Bia transferiu de Infra para TI')
    expect(w.text()).toContain('João Silva')
    const botoes = w.findAll('button').map((b) => b.text())
    expect(botoes).toContain('Assumir')
    expect(botoes).toContain('Transferir')
    expect(botoes).not.toContain('Comentar e concluir')
    expect(botoes).not.toContain('Devolver para a fila')

    await w
      .findAll('button')
      .find((b) => b.text() === 'Assumir')!
      .trigger('click')
    await vi.waitFor(() =>
      expect(feitas.find((r) => r.caminho.endsWith('/assign'))?.corpo).toEqual({ assignee: 'me' }),
    )
  })

  it('aguardar exige o comentário', async () => {
    simularApi({
      'GET /api/v1/tickets/1000': [200, { ...CHAMADO, allowed_actions: ['comment', 'wait'] }],
      'GET /api/v1/tickets/1000/comments': [200, { items: [] }],
      'GET /api/v1/tickets/1000/events': [200, { items: [] }],
      'GET /api/v1/teams': [200, GRUPOS],
    })
    const w = montar(TicketView, { props: { numero: '1000' } })
    await vi.waitFor(() => expect(w.text()).toContain('Comentar e aguardar'))
    await w
      .findAll('button')
      .find((b) => b.text() === 'Comentar e aguardar')!
      .trigger('click')
    expect(w.get('[role=alert]').text()).toBe('Escreva no comentário o que se está aguardando.')
  })

  it('sem acesso mostra a mensagem do 403', async () => {
    simularApi({
      'GET /api/v1/tickets/1000': [
        403,
        { status: 403, detail: 'Você não tem acesso a este chamado.' },
      ],
      'GET /api/v1/tickets/1000/comments': [403, { status: 403 }],
      'GET /api/v1/tickets/1000/events': [403, { status: 403 }],
      'GET /api/v1/teams': [200, GRUPOS],
    })
    const w = montar(TicketView, { props: { numero: '1000' } })
    await vi.waitFor(() => expect(w.text()).toContain('Você não tem acesso a este chamado'))
  })
})
