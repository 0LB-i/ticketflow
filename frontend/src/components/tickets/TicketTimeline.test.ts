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
          attachments: [],
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

  it('mostra os anexos de cada comentário, sem repetir as imagens que já estão no texto', () => {
    const autor = { id: ME_AGENTE.id, full_name: 'Ana' }
    const PRINT = '00000000-0000-0000-0000-0000000000f1'
    const anexo = (id: string, filename: string, comment_id: string | null) => ({
      id,
      filename,
      content_type: filename.endsWith('.png') ? 'image/png' : 'application/pdf',
      size_bytes: 2048,
      comment_id,
      uploaded_by: autor,
      created_at: '2026-10-10T12:00:00Z',
    })
    const w = montar(TicketTimeline, {
      props: {
        chamado: {
          number: 1000,
          created_by: autor,
          created_at: '2026-10-10T12:00:00Z',
          description: 'Veja o manual',
          attachments: [
            anexo('a1', 'manual.pdf', null),
            anexo('a2', 'contrato.pdf', 'c1'),
            anexo(PRINT, 'print.png', 'c1'),
          ],
        } as never,
        comentarios: [
          {
            id: 'c1',
            author: autor,
            body: `Segue o print:\n\n![print.png](/api/v1/attachments/${PRINT})`,
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
    const [registro, comentario] = w.findAll('ol > li')
    expect(registro!.text()).toContain('manual.pdf')
    expect(registro!.text()).not.toContain('contrato.pdf')
    expect(comentario!.text()).toContain('contrato.pdf')
    expect(comentario!.text()).toContain('2 KB')
    expect(comentario!.find(`img[src="/api/v1/attachments/${PRINT}"]`).exists()).toBe(true)
    expect(comentario!.findAll('a').map((a) => a.text())).not.toContain('print.png')
  })
})
