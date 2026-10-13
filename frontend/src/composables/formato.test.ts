import { describe, expect, it } from 'vitest'

import {
  dataEHora,
  formatarDuracao,
  formatarHoraMinuto,
  instante,
  lerDuracao,
  mascararHoraMinuto,
  TEMPOS_SUGERIDOS,
} from './formato'

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

  it('mostra os minutos como hh:mm', () => {
    expect([20, 90, 1440].map(formatarHoraMinuto)).toEqual(['00:20', '01:30', '24:00'])
  })

  it('lista 20 e 30 min, de 15 em 15 até 3 h e de hora em hora até 24 h', () => {
    const lista = TEMPOS_SUGERIDOS.map(formatarHoraMinuto)
    expect(lista.slice(0, 13)).toEqual([
      '00:20',
      '00:30',
      '00:45',
      '01:00',
      '01:15',
      '01:30',
      '01:45',
      '02:00',
      '02:15',
      '02:30',
      '02:45',
      '03:00',
      '04:00',
    ])
    expect(lista.at(-1)).toBe('24:00')
    expect(lista).toHaveLength(33)
  })

  it('a máscara preenche hh:mm pela direita', () => {
    expect(
      ['', 'abc', '0', '4', '45', '130', '0130', '1305', '12345', '1:3'].map(mascararHoraMinuto),
    ).toEqual(['', '', '', '00:04', '00:45', '01:30', '01:30', '13:05', '23:45', '00:13'])
  })

  it('lê hh:mm e recusa minutos acima de 59 ou zero', () => {
    expect(lerDuracao('01:30')).toBe(90)
    expect(lerDuracao('24:00')).toBe(1440)
    expect(lerDuracao('')).toBeNull()
    for (const texto of ['00:75', '00:00', '1:30', '1h30'])
      expect(lerDuracao(texto)).toBeUndefined()
  })
})
