import { afterEach, describe, expect, it, vi } from 'vitest'

import { escolher, montar, simularApi } from '@/test/setup'

import ReportsView from './ReportsView.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  document.body.innerHTML = ''
})

const EXPEDIENTE = {
  weekdays: [0, 1, 2, 3, 4],
  start: '08:00:00',
  end: '18:00:00',
  holidays: [],
}
const ANA = '00000000-0000-0000-0000-00000000000a'
const BIA = '00000000-0000-0000-0000-00000000000b'
const RELATORIO = {
  start: '2026-10-01',
  end: '2026-10-31',
  work_hours: EXPEDIENTE,
  totals: { minutes: 135, overtime_minutes: 60, tasks: 3, tickets_opened: 2, tickets_closed: 1 },
  people: [
    { id: ANA, name: 'Ana', minutes: 135, overtime_minutes: 60, tasks: 3, tickets_closed: 1 },
  ],
  clients: [
    { id: null, name: null, minutes: 15, tickets_opened: 1, tickets_closed: 0 },
    {
      id: '00000000-0000-0000-0000-0000000000c1',
      name: 'Padaria',
      minutes: 120,
      tickets_opened: 1,
      tickets_closed: 1,
    },
  ],
  days: [{ date: '2026-10-05', minutes: 135, overtime_minutes: 60 }],
  overtime_tasks: [
    {
      ticket_number: 1000,
      ticket_title: 'Servidor parado',
      person: 'Ana',
      done_at: '2026-10-05T22:00:00Z',
      minutes: 90,
      overtime_minutes: 60,
    },
  ],
}

describe('ReportsView', () => {
  it('mostra os totais do mês atual e filtra por pessoa', async () => {
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-10-15T12:00:00Z') })
    const feitas = simularApi({
      'GET /api/v1/reports/options': [
        200,
        {
          teams: [],
          people: [
            { id: ANA, name: 'Ana' },
            { id: BIA, name: 'Bia' },
          ],
        },
      ],
      'GET /api/v1/reports': [200, RELATORIO],
    })
    const w = montar(ReportsView)
    await vi.waitFor(() => expect(w.text()).toContain('2h15'))
    expect(w.text()).toContain('Horas extras')
    expect(w.text()).toContain('1h')
    const primeira = feitas.find((r) => r.caminho === '/api/v1/reports')!
    expect(Object.fromEntries(primeira.query)).toEqual({ start: '2026-10-01', end: '2026-10-31' })
    // Sem grupos supervisionados, o filtro de grupo não aparece
    expect(w.text()).not.toContain('Todos os grupos')

    await escolher('Pessoa', 'Bia')
    await vi.waitFor(() =>
      expect(
        feitas
          .filter((r) => r.caminho === '/api/v1/reports')
          .at(-1)!
          .query.get('person'),
      ).toBe(BIA),
    )
  })

  it('quem só vê o próprio trabalho não escolhe pessoa', async () => {
    simularApi({
      'GET /api/v1/reports/options': [200, { teams: [], people: [{ id: ANA, name: 'Ana' }] }],
      'GET /api/v1/reports': [200, RELATORIO],
    })
    const w = montar(ReportsView)
    await vi.waitFor(() => expect(w.text()).toContain('2h15'))
    expect(w.text()).not.toContain('Todas as pessoas')
  })

  it('erro da API aparece na tela', async () => {
    simularApi({
      'GET /api/v1/reports/options': [200, { teams: [], people: [] }],
      'GET /api/v1/reports': [403, { detail: 'Você só pode ver os seus próprios números.' }],
    })
    const w = montar(ReportsView)
    await vi.waitFor(() => expect(w.text()).toContain('Você só pode ver os seus próprios números.'))
  })
})
