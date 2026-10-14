import { afterEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import { criarRouter } from '@/router'
import { escolher, ME_AGENTE, montar, simularApi } from '@/test/setup'

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
const STATUS = {
  items: [
    { id: 1, name: 'Pendente', kind: 'open' },
    { id: 2, name: 'Aguardando cliente', kind: 'waiting' },
    { id: 5, name: 'Entregue', kind: 'closed' },
    { id: 3, name: 'Concluído', kind: 'closed' },
    { id: 4, name: 'Cancelado', kind: 'canceled' },
  ],
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
const PADARIA = {
  id: '00000000-0000-0000-0000-0000000000e1',
  kind: 'company',
  name: 'Padaria Pão Quente',
  trade_name: 'Pão Quente',
  document: '11222333000181',
  email: 'contato@paoquente.com.br',
  phone: '1133334444',
  city: 'São Paulo',
  state: 'SP',
  is_active: true,
}
/** Campo de texto pelo rótulo. */
function campo(w: ReturnType<typeof montar>, rotulo: string) {
  const label = w.findAll('label').find((l) => l.text() === rotulo)!
  return w.get(`#${CSS.escape(label.attributes('for')!)}`)
}
/** Digita no seletor de cliente e escolhe o resultado, como um usuário. */
async function escolherCliente(w: ReturnType<typeof montar>, nome: string) {
  await campo(w, 'Cliente').setValue(nome.slice(0, 4))
  const item = await vi.waitFor(() => {
    const encontrado = [...document.querySelectorAll('[role=option]')].find((o) =>
      o.textContent?.includes(nome),
    )
    expect(encontrado).toBeTruthy()
    return encontrado as HTMLElement
  })
  item.click()
}

describe('NewTicketView', () => {
  it('registra com o grupo, o status e o responsável escolhidos', async () => {
    const feitas = simularApi({
      'GET /api/v1/me': [200, { ...ME, permissions: ['ticket.create', 'ticket.transition'] }],
      'GET /api/v1/teams': [200, GRUPOS],
      'GET /api/v1/statuses': [200, STATUS],
      'GET /api/v1/clients': [200, { items: [PADARIA], total: 1 }],
      'POST /api/v1/tickets': [201, { number: 1000, title: 'Impressora parada' }],
    })
    const router = criarRouter()
    const w = montar(NewTicketView, { global: { plugins: [router] } })
    await router.push('/chamados/novo')

    await vi.waitFor(() => expect(w.text()).toContain('Pendente')) // o padrão
    await escolher('Status', 'Entregue')
    await w.get('input[type=text]').setValue('Impressora parada')
    await escolherCliente(w, 'Padaria Pão Quente')
    await campo(w, 'Contato').setValue('Maria')
    await w.get('button[aria-label="Remover Ana"]').trigger('click') // ninguém: fila do grupo
    expect(w.text()).toContain('fica na fila do grupo')
    await w.get('form').trigger('submit')

    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/chamados/1000'))
    expect(feitas.find((r) => r.metodo === 'POST')!.corpo).toEqual({
      title: 'Impressora parada',
      description: '',
      team_id: TI,
      status_id: 5,
      started_at: null,
      client_id: PADARIA.id,
      beneficiary_name: 'Maria',
      assignee: null,
      co_assignee_ids: [],
      watcher_ids: [],
      mention_ids: [],
      attachment_ids: [],
    })
  })

  it('o usuário começa com quem registra e aceita outras pessoas ou o grupo todo', async () => {
    const feitas = simularApi({
      'GET /api/v1/me': [200, ME],
      'GET /api/v1/teams': [200, GRUPOS],
      'GET /api/v1/statuses': [200, STATUS],
      'POST /api/v1/tickets': [201, { number: 1001, title: 'Para o grupo' }],
    })
    const router = criarRouter()
    const w = montar(NewTicketView, { global: { plugins: [router] } })
    await router.push('/chamados/novo')
    await vi.waitFor(() => expect(w.find('button[aria-label="Remover Ana"]').exists()).toBe(true))

    await w.get('button[aria-label="Remover Ana"]').trigger('click')
    await escolher('Usuários', 'Bia')
    await vi.waitFor(() => expect(w.find('button[aria-label="Remover Bia"]').exists()).toBe(true))
    await escolher('Usuários', 'Todas as pessoas do grupo')
    await vi.waitFor(() => expect(w.find('button[aria-label="Remover Ana"]').exists()).toBe(true))
    await w.get('input[type=text]').setValue('Para o grupo')
    await w.get('form').trigger('submit')

    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/chamados/1001'))
    // Quem registra fica como principal; os demais vão em co_assignee_ids.
    expect(feitas.find((r) => r.metodo === 'POST')!.corpo).toMatchObject({
      assignee: 'me',
      co_assignee_ids: [BIA],
    })
  })

  it('relê os grupos ao abrir: quem foi incluído num grupo depois do login já registra', async () => {
    simularApi({
      'GET /api/v1/me': [200, ME],
      'GET /api/v1/teams': [200, GRUPOS],
      'GET /api/v1/statuses': [200, STATUS],
    })
    const w = montar(NewTicketView)
    useAuthStore().me = { ...ME, teams: [] } // dados do login, antes de entrar no grupo
    await vi.waitFor(() => expect(w.find('form').exists()).toBe(true))
    expect(w.text()).not.toContain('ainda não é membro')
  })

  it('o início acompanha a hora atual até a pessoa mudar', async () => {
    const feitas = simularApi({
      'GET /api/v1/me': [200, ME],
      'GET /api/v1/teams': [200, GRUPOS],
      'GET /api/v1/statuses': [200, STATUS],
      'POST /api/v1/tickets': [201, { number: 1002, title: 'Começou cedo' }],
    })
    const router = criarRouter()
    const w = montar(NewTicketView, { global: { plugins: [router] } })
    await router.push('/chamados/novo')
    await vi.waitFor(() => expect(w.find('input[type=date]').exists()).toBe(true))
    expect(w.text()).not.toContain('Ajustado à mão')

    await w.get('input[type=date]').setValue('2026-10-01')
    await w.get('input[type=time]').setValue('07:45')
    expect(w.text()).toContain('Ajustado à mão')
    await w.get('input[type=text]').setValue('Começou cedo')
    await w.get('form').trigger('submit')

    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/chamados/1002'))
    expect(feitas.find((r) => r.metodo === 'POST')!.corpo).toMatchObject({
      started_at: '2026-10-01T10:45:00.000Z',
    })
  })

  it('sem ticket.transition, não escolhe o status: vai como Pendente', async () => {
    simularApi({
      'GET /api/v1/me': [200, ME],
      'GET /api/v1/teams': [200, GRUPOS],
      'GET /api/v1/statuses': [200, STATUS],
    })
    const w = montar(NewTicketView, { global: { plugins: [criarRouter()] } })
    await vi.waitFor(() => expect(w.find('form').exists()).toBe(true))
    expect(w.text()).not.toContain('Status')
  })

  it('não envia sem título', async () => {
    // O router faz a navegação inicial ao ser instalado, e o guard carrega o /me.
    const feitas = simularApi({
      'GET /api/v1/me': [200, ME],
      'GET /api/v1/teams': [200, GRUPOS],
      'GET /api/v1/statuses': [200, STATUS],
    })
    const w = montar(NewTicketView, { global: { plugins: [criarRouter()] } })
    await vi.waitFor(() => expect(w.find('form').exists()).toBe(true))
    await w.get('form').trigger('submit')
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
  team: { id: TI, name: 'TI' },
  category: { id: IMPRESSAO, name: 'Impressão', path: 'Impressão' },
  department: null,
  client: { id: '00000000-0000-0000-0000-0000000000e1', name: 'Padaria Pão Quente' },
  beneficiary_name: 'Maria',
  assignee: null,
  started_at: '2026-10-10T11:30:00Z',
  created_at: '2026-10-10T12:00:00Z',
  updated_at: '2026-10-10T12:00:00Z',
  description: 'Aparece **offline**.',
  created_by: { id: BIA, full_name: 'Bia' },
  resolution_code: null,
  reopened_count: 0,
  closed_at: null,
  co_assignees: [],
  watchers: [],
  attachments: [],
  time_spent_minutes: 0,
  time_by_person: [],
  allowed_actions: ['assign_self', 'comment', 'edit', 'transfer', 'watch_self'],
}

describe('TicketView', () => {
  it('mostra o chamado, a linha do tempo e só as ações permitidas', async () => {
    const feitas = simularApi({
      'GET /api/v1/tickets/1000': [200, CHAMADO],
      'GET /api/v1/tickets/1000/comments': [200, { items: [] }],
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
    // O histórico (assumiu, devolveu, acompanha…) não aparece na tela: nem é buscado
    expect(feitas.some((r) => r.caminho.endsWith('/events'))).toBe(false)
    expect(w.text()).toContain('10/10/2026, 08:30') // início, no fuso de São Paulo
    expect(w.text()).toContain('Padaria Pão Quente')
    expect(w.text()).toContain('Maria')
    const botoes = w.findAll('button').map((b) => b.text())
    expect(botoes).toContain('Assumir')
    expect(botoes).toContain('Transferir')
    expect(botoes).not.toContain('Concluir chamado')
    expect(botoes).not.toContain('Devolver para a fila')

    await w
      .findAll('button')
      .find((b) => b.text() === 'Assumir')!
      .trigger('click')
    await vi.waitFor(() =>
      expect(feitas.find((r) => r.caminho.endsWith('/assign'))?.corpo).toEqual({ assignee: 'me' }),
    )
  })

  it('marcar como entregue fica no fim da lateral, em dourado, e muda o status num clique', async () => {
    const STATUS_LISTA = {
      items: [
        { id: 1, name: 'Pendente', kind: 'open' },
        { id: 5, name: 'Entregue', kind: 'closed' },
      ],
    }
    const feitas = simularApi({
      'GET /api/v1/tickets/1000': [200, { ...CHAMADO, allowed_actions: ['comment', 'set_status'] }],
      'GET /api/v1/tickets/1000/comments': [200, { items: [] }],
      'GET /api/v1/teams': [200, GRUPOS],
      'GET /api/v1/statuses': [200, STATUS_LISTA],
      'PATCH /api/v1/tickets/1000': [200, CHAMADO],
    })
    const w = montar(TicketView, { props: { numero: '1000' } })
    await vi.waitFor(() => expect(w.text()).toContain('Marcar como entregue'))
    expect(w.findAll('form button').map((b) => b.text())).not.toContain('Marcar como entregue')
    const botoes = w.get('aside').findAll(':scope > button')
    const entregar = botoes.at(-1)!
    expect(entregar.text()).toBe('Marcar como entregue') // o último da lateral
    expect(entregar.classes()).toContain('bg-gold')

    await entregar.trigger('click') // sem janela de confirmação
    await vi.waitFor(() =>
      expect(feitas.find((r) => r.metodo === 'PATCH')?.corpo).toEqual({ status_id: 5 }),
    )
  })

  it('mostra o tempo de cada andamento e a soma por pessoa na lateral', async () => {
    simularApi({
      'GET /api/v1/tickets/1000': [
        200,
        {
          ...CHAMADO,
          allowed_actions: ['comment', 'resume'],
          time_spent_minutes: 135,
          time_by_person: [
            { id: ANA, full_name: 'Ana', minutes: 90 },
            { id: BIA, full_name: 'Bia', minutes: 45 },
          ],
        },
      ],
      'GET /api/v1/tickets/1000/comments': [
        200,
        {
          items: [
            {
              id: 'c1',
              author: { id: ANA, full_name: 'Ana' },
              body: 'Troquei o toner.',
              is_solution: false,
              time_spent_minutes: 90,
              created_at: '2026-10-10T12:10:00Z',
              edited_at: null,
              done_at: '2026-10-10T12:10:00Z',
            },
          ],
        },
      ],
      'GET /api/v1/teams': [200, GRUPOS],
    })
    const w = montar(TicketView, { props: { numero: '1000' } })
    await vi.waitFor(() => expect(w.text()).toContain('Troquei o toner.'))
    expect(w.get('ol > li:nth-child(2)').text()).toContain('Tempo gasto:1h30')
    const lateral = w.get('section[aria-labelledby=tempo-titulo]').text()
    expect(lateral).toContain('Total: 2h15')
    expect(lateral).toContain('Ana1h30')
    expect(lateral).toContain('Bia45min')

    // Minutos acima de 59 não valem; e tempo sem comentário não tem onde ficar
    const tempo = w
      .findAll('input')
      .find((i) => i.element.labels?.[0]?.textContent === 'Tempo gasto')!
    await tempo.setValue('75')
    expect(w.text()).toContain('Informe horas e minutos válidos, como 01:30.')
    await tempo.setValue('30')
    expect((tempo.element as HTMLInputElement).value).toBe('00:30')
    await w
      .findAll('button')
      .find((b) => b.text() === 'Retomar')!
      .trigger('click')
    expect(w.get('[role=alert]').text()).toBe('Descreva a tarefa feita nesse tempo.')
  })

  it('sem acesso mostra a mensagem do 403', async () => {
    simularApi({
      'GET /api/v1/tickets/1000': [
        403,
        { status: 403, detail: 'Você não tem acesso a este chamado.' },
      ],
      'GET /api/v1/tickets/1000/comments': [403, { status: 403 }],
      'GET /api/v1/teams': [200, GRUPOS],
    })
    const w = montar(TicketView, { props: { numero: '1000' } })
    await vi.waitFor(() => expect(w.text()).toContain('Você não tem acesso a este chamado'))
  })
})
