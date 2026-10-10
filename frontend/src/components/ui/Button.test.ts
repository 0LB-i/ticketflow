import { describe, expect, it } from 'vitest'

import { montar } from '@/test/setup'

import Button from './Button.vue'

describe('Button', () => {
  it('é do tipo button por padrão e emite clique', async () => {
    const w = montar(Button, { slots: { default: 'Registrar' } })
    expect(w.attributes('type')).toBe('button')
    await w.trigger('click')
    expect(w.emitted('click')).toHaveLength(1)
  })

  it('usa os tokens da variante, nunca cores diretas', () => {
    const w = montar(Button, { props: { variant: 'danger' } })
    expect(w.classes()).toContain('bg-danger')
    expect(w.classes().some((c) => c.includes('orange'))).toBe(false)
  })
})
