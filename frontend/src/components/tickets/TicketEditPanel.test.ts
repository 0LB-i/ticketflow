import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Chamado } from '@/composables/chamados'
import { montar, simularApi } from '@/test/setup'

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
  beneficiary_name: null,
  assignee: null,
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
  watchers: [],
  allowed_actions: ['set_priority'],
}

describe('TicketEditPanel', () => {
  it('mudar a urgência de uma prioridade forçada volta para a matriz, como a API grava', async () => {
    const feitas = simularApi({ 'PATCH /api/v1/tickets/1000': [200, CHAMADO] })
    montar(TicketEditPanel, { props: { chamado: CHAMADO, open: false } }).setProps({
      open: true,
    })
    const opcao = await vi.waitFor(() => {
      const radio = [...document.querySelectorAll('label')].find((l) =>
        l.textContent?.includes('Pode esperar'),
      )
      expect(radio).toBeTruthy()
      return radio!.querySelector('input')!
    })
    expect(document.body.textContent).not.toContain('Calculada (impacto × urgência)')

    opcao.click()
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain('Calculada (impacto × urgência)'),
    )
    document.querySelector<HTMLFormElement>('#form-editar-chamado')!.requestSubmit()
    await vi.waitFor(() =>
      expect(feitas.find((r) => r.metodo === 'PATCH')?.corpo).toEqual({
        urgency: 1,
        priority: null,
      }),
    )
  })
})
