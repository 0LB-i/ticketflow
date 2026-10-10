import { describe, expect, it } from 'vitest'

import { montar } from '@/test/setup'

import PriorityBadge from './PriorityBadge.vue'
import StatusBadge from './StatusBadge.vue'

describe('StatusBadge', () => {
  it('usa o nome padrão do status e a cor do kind', () => {
    const w = montar(StatusBadge, { props: { kind: 'waiting' } })
    expect(w.text()).toBe('Aguardando cliente')
    expect(w.classes()).toContain('text-violet-fg')
  })

  it('aceita o nome dado pelo administrador', () => {
    const w = montar(StatusBadge, { props: { kind: 'open', label: 'Em andamento' } })
    expect(w.text()).toBe('Em andamento')
    expect(w.classes()).toContain('text-blue-fg')
  })
})

describe('PriorityBadge', () => {
  it('tem texto e ícone, não só cor', () => {
    const w = montar(PriorityBadge, { props: { priority: 4 } })
    expect(w.text()).toContain('Crítica')
    expect(w.text()).toContain('▲')
  })
})
