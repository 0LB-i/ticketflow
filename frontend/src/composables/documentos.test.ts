import { describe, expect, it } from 'vitest'

import {
  cnpjValido,
  cpfValido,
  formatarCep,
  formatarDocumento,
  formatarTelefone,
  telefoneValido,
} from './documentos'

describe('documentos', () => {
  it('valida CPF pelos dígitos verificadores', () => {
    expect(cpfValido('529.982.247-25')).toBe(true)
    expect(cpfValido('529.982.247-24')).toBe(false)
    expect(cpfValido('111.111.111-11')).toBe(false)
  })

  it('valida CNPJ numérico e alfanumérico', () => {
    expect(cnpjValido('11.222.333/0001-81')).toBe(true)
    expect(cnpjValido('12.abc.345/01de-35')).toBe(true)
    expect(cnpjValido('12.ABC.345/01DE-36')).toBe(false)
  })

  it('formata enquanto se digita', () => {
    expect(formatarDocumento('52998224725', 'person')).toBe('529.982.247-25')
    expect(formatarDocumento('5299', 'person')).toBe('529.9')
    expect(formatarDocumento('12abc34501de35', 'company')).toBe('12.ABC.345/01DE-35')
    expect(formatarTelefone('11987654321')).toBe('(11) 98765-4321')
    expect(formatarTelefone('+55 11 3333-4444')).toBe('(11) 3333-4444')
    expect(formatarCep('01310100')).toBe('01310-100')
  })

  it('telefone precisa do DDD', () => {
    expect(telefoneValido('(11) 3333-4444')).toBe(true)
    expect(telefoneValido('3333-4444')).toBe(false)
  })
})
