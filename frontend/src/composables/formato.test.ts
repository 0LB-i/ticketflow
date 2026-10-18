import { describe, expect, it } from 'vitest'

import { dataEHora, formatarDuracao } from './formato'

describe('data e hora no fuso de São Paulo', () => {
  it('separa um instante na data e na hora dos inputs', () => {
    expect(dataEHora(new Date('2026-10-10T02:30:00Z'))).toEqual({
      data: '2026-10-09',
      hora: '23:30',
    })
  })
})

describe('tempo gasto', () => {
  it('formata os minutos em horas e minutos', () => {
    expect([45, 60, 90, 125, 6000].map(formatarDuracao)).toEqual([
      '45min',
      '1h',
      '1h30',
      '2h05',
      '100h',
    ])
  })
})
