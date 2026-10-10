import { describe, expect, it } from 'vitest'

import { dataEHora, instante } from './formato'

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
