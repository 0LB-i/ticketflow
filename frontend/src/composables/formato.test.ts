import { describe, expect, it } from 'vitest'

import { dataEHora, formatarDuracao, instante, lerDuracao } from './formato'

describe('data e hora no fuso de São Paulo', () => {
  it('separa um instante na data e na hora dos inputs', () => {
    expect(dataEHora(new Date('2026-10-10T02:30:00Z'))).toEqual({
      data: '2026-10-09',
      hora: '23:30',
    })
  })

  it('junta a data e a hora digitadas de volta no instante', () => {
    expect(instante('2026-10-09', '23:30').toISOString()).toBe('2026-10-10T02:30:00.000Z')
    expect(instante('2026-01-01', '00:00').toISOString()).toBe('2026-01-01T03:00:00.000Z')
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

  it('lê os jeitos comuns de digitar um tempo', () => {
    expect(lerDuracao('1:30')).toBe(90)
    expect(lerDuracao('1h30')).toBe(90)
    expect(lerDuracao(' 1h 30min ')).toBe(90)
    expect(lerDuracao('2H')).toBe(120)
    expect(lerDuracao('45min')).toBe(45)
    expect(lerDuracao('45 m')).toBe(45)
    expect(lerDuracao(formatarDuracao(125))).toBe(125)
    expect(lerDuracao('')).toBeNull()
  })

  it('recusa o que é ambíguo ou inválido', () => {
    for (const texto of ['30', '1:75', '0:00', '0min', 'abc', '1,5h', '1001h']) {
      expect(lerDuracao(texto)).toBeUndefined()
    }
  })
})
