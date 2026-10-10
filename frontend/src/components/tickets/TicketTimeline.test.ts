import { afterEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import { ME_AGENTE, montar } from '@/test/setup'

import TicketTimeline from './TicketTimeline.vue'

afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('TicketTimeline', () => {
  it('o botão de editar o comentário some quando acaba o prazo', async () => {
    vi.useFakeTimers({ now: new Date('2026-10-10T12:09:50Z') })
    const autor = { id: ME_AGENTE.id, full_name: 'Ana' }
    const w = montar(TicketTimeline, {
      props: {
        chamado: {
          number: 1000,
          created_by: autor,
          created_at: '2026-10-10T12:00:00Z',
          description: '',
        } as never,
        comentarios: [
          {
            id: 'c1',
            author: autor,
            body: 'Reiniciei a impressora.',
            is_solution: false,
            created_at: '2026-10-10T12:00:00Z',
            edited_at: null,
            editable_until: '2026-10-10T12:10:00Z',
          },
        ],
        eventos: [],
        pessoas: [],
      },
    })
    useAuthStore().me = { ...ME_AGENTE }
    await w.vm.$nextTick()
    expect(w.findAll('button').map((b) => b.text())).toContain('Editar')

    vi.advanceTimersByTime(30_000)
    await w.vm.$nextTick()
    expect(w.findAll('button').map((b) => b.text())).not.toContain('Editar')
  })
})
