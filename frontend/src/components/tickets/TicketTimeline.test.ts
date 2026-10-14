import { afterEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import { ME_AGENTE, montar, simularApi } from '@/test/setup'

import TicketTimeline from './TicketTimeline.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('TicketTimeline', () => {
  it('o autor edita (texto, tempo, data e hora) e remove a tarefa, sem prazo', async () => {
    const feitas = simularApi({
      'PATCH /api/v1/tickets/1000/comments/c1': [200, {}],
      'DELETE /api/v1/tickets/1000/comments/c1': [204],
    })
    const autor = { id: ME_AGENTE.id, full_name: 'Ana' }
    const tarefa = (id: string, author: typeof autor) => ({
      id,
      author,
      body: 'Reiniciei a impressora.',
      is_solution: false,
      time_spent_minutes: 90,
      done_at: '2026-10-01T13:00:00Z', // dias atrás: não há mais prazo
      created_at: '2026-10-01T13:00:00Z',
      edited_at: null,
    })
    const w = montar(TicketTimeline, {
      props: {
        chamado: {
          number: 1000,
          created_by: autor,
          created_at: '2026-10-01T12:00:00Z',
          description: '',
          attachments: [],
        } as never,
        comentarios: [tarefa('c1', autor), tarefa('c2', { id: 'outra', full_name: 'Bia' })],
        pessoas: [],
      },
    })
    useAuthStore().me = { ...ME_AGENTE }
    await w.vm.$nextTick()
    const [minha, deOutra] = w.findAll('ol > li').slice(1)
    expect(minha!.text()).toContain('01/10/2026, 10:00') // a data da tarefa, no fuso de SP
    const botoes = (li: typeof minha) => li!.findAll('button').map((b) => b.text())
    expect(botoes(minha)).toEqual(['Editar', 'Remover'])
    expect(botoes(deOutra)).toEqual([])

    const clicar = (texto: string) =>
      minha!
        .findAll('button')
        .find((b) => b.text() === texto)!
        .trigger('click')
    await clicar('Editar')
    expect((minha!.find('input[type=date]').element as HTMLInputElement).value).toBe('2026-10-01')
    expect((minha!.find('input[type=time]').element as HTMLInputElement).value).toBe('10:00')
    await minha!.find('input[type=time]').setValue('08:15')
    await clicar('Salvar')
    await vi.waitFor(() =>
      expect(feitas.find((r) => r.metodo === 'PATCH')?.corpo).toMatchObject({
        body: 'Reiniciei a impressora.',
        time_spent_minutes: 90,
        done_at: '2026-10-01T11:15:00.000Z',
      }),
    )

    await vi.waitFor(() => expect(botoes(minha)).toContain('Remover'))
    await clicar('Remover')
    expect(minha!.text()).toContain('Remover esta tarefa?')
    expect(feitas.some((r) => r.metodo === 'DELETE')).toBe(false) // só depois de confirmar
    await clicar('Remover')
    await vi.waitFor(() => expect(feitas.some((r) => r.metodo === 'DELETE')).toBe(true))
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
            time_spent_minutes: null,
            created_at: '2026-10-10T12:00:00Z',
            edited_at: null,
            done_at: '2026-10-10T12:00:00Z',
          },
        ],
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
