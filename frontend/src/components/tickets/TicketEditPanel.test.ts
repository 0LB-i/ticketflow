import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Chamado } from '@/composables/chamados'
import { escolher, montar, simularApi } from '@/test/setup'

import TicketEditPanel from './TicketEditPanel.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const CHAMADO: Chamado = {
  id: '00000000-0000-0000-0000-0000000000d1',
  number: 1000,
  title: 'Impressora parada',
  type: 'incident',
  status: { id: 1, name: 'Pendente', kind: 'open' },
  priority: 4,
  team: { id: 't', name: 'TI' },
  category: { id: 'c', name: 'Impressão', path: 'Impressão' },
  department: null,
  client: null,
  beneficiary_name: null,
  assignee: null,
  started_at: '2026-10-10T11:30:00Z',
  created_at: '2026-10-10T12:00:00Z',
  updated_at: '2026-10-10T12:00:00Z',
  description: '',
  impact: 2,
  urgency: 3,
  priority_overridden: true,
  created_by: { id: 'b', full_name: 'Bia' },
  resolution_code: null,
  reopened_count: 0,
  closed_at: null,
  co_assignees: [],
  watchers: [],
  attachments: [],
  allowed_actions: ['set_priority'],
}

describe('TicketEditPanel', () => {
  it('muda o status sem as exigências do fluxo', async () => {
    const feitas = simularApi({
      'GET /api/v1/statuses': [
        200,
        {
          items: [
            { id: 1, name: 'Pendente', kind: 'open' },
            { id: 5, name: 'Entregue', kind: 'closed' },
          ],
        },
      ],
      'PATCH /api/v1/tickets/1000': [200, CHAMADO],
    })
    montar(TicketEditPanel, {
      props: { chamado: { ...CHAMADO, allowed_actions: ['set_status'] }, open: false },
    }).setProps({ open: true })
    await vi.waitFor(() => expect(document.body.textContent).toContain('Pendente'))

    await escolher('Status', 'Entregue')
    document.querySelector<HTMLFormElement>('#form-editar-chamado')!.requestSubmit()
    await vi.waitFor(() =>
      expect(feitas.find((r) => r.metodo === 'PATCH')?.corpo).toEqual({ status_id: 5 }),
    )
  })

  it('prioridade forçada pode voltar a ser automática', async () => {
    const feitas = simularApi({ 'PATCH /api/v1/tickets/1000': [200, CHAMADO] })
    montar(TicketEditPanel, { props: { chamado: CHAMADO, open: false } }).setProps({
      open: true,
    })
    await vi.waitFor(() => expect(document.querySelector('#form-editar-chamado')).toBeTruthy())

    await escolher('Prioridade', 'Automática')
    document.querySelector<HTMLFormElement>('#form-editar-chamado')!.requestSubmit()
    await vi.waitFor(() =>
      expect(feitas.find((r) => r.metodo === 'PATCH')?.corpo).toEqual({ priority: null }),
    )
  })

  it('troca o contato e tira o cliente: só vai o que mudou', async () => {
    const feitas = simularApi({ 'PATCH /api/v1/tickets/1000': [200, CHAMADO] })
    montar(TicketEditPanel, {
      props: {
        chamado: {
          ...CHAMADO,
          client: { id: 'p', name: 'Padaria Pão Quente' },
          beneficiary_name: 'Maria',
          allowed_actions: ['edit'],
        },
        open: false,
      },
    }).setProps({ open: true })
    const campo = await vi.waitFor(() => {
      const label = [...document.querySelectorAll('label')].find((l) => l.textContent === 'Contato')
      expect(label).toBeTruthy()
      return document.getElementById(label!.htmlFor) as HTMLInputElement
    })
    expect(campo.value).toBe('Maria')
    campo.value = '  João '
    campo.dispatchEvent(new Event('input'))
    document.querySelector<HTMLButtonElement>('[aria-label="Tirar o cliente"]')!.click()

    document.querySelector<HTMLFormElement>('#form-editar-chamado')!.requestSubmit()
    await vi.waitFor(() =>
      expect(feitas.find((r) => r.metodo === 'PATCH')?.corpo).toEqual({
        client_id: null,
        beneficiary_name: 'João',
      }),
    )
  })
})
