import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { simularApi } from '@/test/setup'

import en from './en.json'
import { definirIdioma, i18n } from './index'
import ptBR from './pt-BR.json'

/** Chave → marcadores ({nome}) de cada mensagem. */
function achatar(obj: object, prefixo = ''): Map<string, string[]> {
  const saida = new Map<string, string[]>()
  for (const [chave, valor] of Object.entries(obj)) {
    if (typeof valor === 'object') {
      for (const [k, v] of achatar(valor, `${prefixo}${chave}.`)) saida.set(k, v)
    } else {
      saida.set(
        `${prefixo}${chave}`,
        [...String(valor).matchAll(/\{(\w+)\}/g)].map((m) => m[1]!).sort(),
      )
    }
  }
  return saida
}

afterEach(() => {
  vi.unstubAllGlobals()
  definirIdioma('pt-BR')
})

describe('idiomas', () => {
  it('o inglês tem as mesmas mensagens e marcadores do português', () => {
    expect(Object.fromEntries(achatar(en))).toEqual(Object.fromEntries(achatar(ptBR)))
  })

  it('nenhuma mensagem usa os caracteres especiais do vue-i18n (@ e |)', () => {
    const textos = JSON.stringify([en, ptBR])
    expect(textos).not.toMatch(/[@|]/)
  })

  it('troca o idioma da interface, do <html> e das chamadas à API', async () => {
    const feitas = simularApi({ 'GET /api/v1/branding': [200, {}] })
    definirIdioma('en')
    expect(i18n.global.t('chamados.novo')).toBe('New ticket')
    expect(document.documentElement.lang).toBe('en')
    await api.GET('/api/v1/branding')
    expect(feitas[0]!.headers.get('Accept-Language')).toBe('en')
  })
})
