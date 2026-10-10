import { describe, expect, it } from 'vitest'

import type { Evento } from '@/composables/chamados'
import { i18n } from '@/i18n'

import { descreverEvento } from './eventos'

const ANA = { id: 'u-ana', full_name: 'Ana' }
const t = i18n.global.t as (chave: string, params?: Record<string, unknown>) => string
const frase = (type: string, payload: Record<string, unknown>) =>
  descreverEvento({ id: 1, type, actor: ANA, payload, created_at: '' } as Evento, t)
const ref = (id: string, name: string) => ({ id, name })

describe('descreverEvento', () => {
  it.each([
    ['ticket.assigned', { from: null, to: ref('u-ana', 'Ana') }, 'Ana assumiu o chamado'],
    ['ticket.assigned', { from: null, to: ref('u-bia', 'Bia') }, 'Ana atribuiu a Bia'],
    ['ticket.assigned', { from: ref('u-bia', 'Bia'), to: null }, 'Ana devolveu para a fila'],
    [
      'ticket.status_changed',
      { from: ref('1', 'Pendente'), to: ref('3', 'Concluído'), resolution_code: ref('1', 'Feito') },
      'Ana mudou o status de Pendente para Concluído · Feito',
    ],
    [
      'ticket.updated',
      {
        changes: { priority: {}, priority_overridden: {}, title: {} },
        reason: 'Diretoria parada',
      },
      'Ana alterou prioridade, título · motivo: Diretoria parada',
    ],
    ['watcher.added', { user: ref('u-caio', 'Caio'), kind: 'mentioned' }, 'Ana mencionou Caio'],
    ['watcher.added', { user: ref('u-ana', 'Ana'), kind: 'watcher' }, 'Ana passou a acompanhar'],
    ['watcher.removed', { user: ref('u-caio', 'Caio') }, 'Ana removeu Caio dos observadores'],
  ])('%s', (type, payload, esperado) => {
    expect(frase(type, payload)).toBe(esperado)
  })
})
