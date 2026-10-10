import { describe, expect, it } from 'vitest'

import { contraste, CORES_PADRAO, type Cores, paleta, PALETA_PADRAO, type Tokens } from './paleta'

/** Contrastes exigidos pelo docs/17 §17.3 (WCAG 2.1 AA). */
function conferir(t: Tokens) {
  const fundos = [t.bg, t.surface, t['surface-raised']]
  for (const fundo of fundos) {
    expect(contraste(t.fg, fundo), `texto sobre ${fundo}`).toBeGreaterThanOrEqual(4.5)
    expect(contraste(t.muted, fundo), `texto secundário sobre ${fundo}`).toBeGreaterThanOrEqual(4.5)
    expect(contraste(t.primary, fundo), `link sobre ${fundo}`).toBeGreaterThanOrEqual(4.5)
  }
  expect(contraste(t['on-primary'], t.primary), 'texto do botão').toBeGreaterThanOrEqual(4.5)
  expect(
    contraste(t['on-primary'], t['primary-hover']),
    'botão com o mouse',
  ).toBeGreaterThanOrEqual(4.5)
  expect(contraste(t.primary, t['primary-subtle']), 'item de menu ativo').toBeGreaterThanOrEqual(
    4.5,
  )
  expect(contraste(t['border-input'], t.surface), 'borda de campo').toBeGreaterThanOrEqual(3)
  expect(contraste(t.focus, t.surface), 'contorno de foco').toBeGreaterThanOrEqual(3)
}

const COMBINACOES: [string, Cores][] = [
  ['azul', { brand: '#1D4ED8', neutral: '#64748B', background: '#F8FAFC' }],
  [
    'amarelo claro (difícil de ler)',
    { brand: '#FDE047', neutral: '#A3A3A3', background: '#FFFFFF' },
  ],
  [
    'laranja da marca com cinza claro',
    { brand: '#F97316', neutral: '#D4D4D4', background: '#FFFFFF' },
  ],
  ['marca quase preta', { brand: '#111111', neutral: '#737373', background: '#FFFFFF' }],
  ['verde com fundo bege', { brand: '#16A34A', neutral: '#78716C', background: '#FAF5E9' }],
  ['fundo cinza médio', { brand: '#C2410C', neutral: '#525252', background: '#D4D4D4' }],
]

describe('paleta', () => {
  it('sem personalização usa a paleta original do docs/17', () => {
    expect(paleta(null)).toBe(PALETA_PADRAO)
    expect(paleta({ ...CORES_PADRAO, brand: '#f97316' })).toBe(PALETA_PADRAO)
  })

  it('a paleta original cumpre os contrastes', () => {
    conferir(PALETA_PADRAO.claro)
    conferir(PALETA_PADRAO.escuro)
  })

  it.each(COMBINACOES)('%s: ajusta os tons e cumpre os contrastes', (_, cores) => {
    const p = paleta(cores)
    conferir(p.claro)
    conferir(p.escuro)
    expect(p.claro.brand).toBe(cores.brand)
    expect(p.claro.surface).toBe(cores.background)
  })

  it('cor já legível fica como foi escolhida', () => {
    expect(paleta({ ...CORES_PADRAO, brand: '#1D4ED8' }).claro.primary).toBe('#1D4ED8')
  })
})
