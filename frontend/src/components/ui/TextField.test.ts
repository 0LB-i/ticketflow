import { describe, expect, it } from 'vitest'

import { montar } from '@/test/setup'

import TextField from './TextField.vue'

describe('TextField', () => {
  it('liga rótulo, dica e erro ao campo', () => {
    const w = montar(TextField, {
      props: { label: 'Título', hint: 'Em poucas palavras', error: 'Obrigatório' },
    })
    const input = w.get('input')
    expect(w.get('label').attributes('for')).toBe(input.attributes('id'))
    expect(input.attributes('aria-invalid')).toBe('true')
    const descritos = input.attributes('aria-describedby')!.split(' ')
    expect(descritos.map((id) => w.get(`[id="${id}"]`).text())).toEqual([
      'Em poucas palavras',
      'Obrigatório',
    ])
  })
})
