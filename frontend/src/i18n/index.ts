import { createI18n } from 'vue-i18n'

import en from './en.json'
import ptBR from './pt-BR.json'

export type Mensagens = typeof ptBR
export type Idioma = 'pt-BR' | 'en'
export const IDIOMAS: Idioma[] = ['pt-BR', 'en']

const CHAVE = 'tf-idioma'

/** Último idioma usado neste navegador: evita mostrar outro idioma antes do /me carregar. */
function idiomaSalvo(): Idioma {
  try {
    const salvo = localStorage.getItem(CHAVE)
    if (IDIOMAS.includes(salvo as Idioma)) return salvo as Idioma
  } catch {
    // armazenamento indisponível (modo privado): usa o padrão
  }
  return 'pt-BR'
}

// O tipo Mensagens obriga o inglês a ter as mesmas chaves do português.
export const i18n = createI18n<[Mensagens], Idioma, false>({
  legacy: false,
  locale: idiomaSalvo(),
  fallbackLocale: 'pt-BR',
  messages: { 'pt-BR': ptBR, en },
})

export function idiomaAtual(): Idioma {
  return i18n.global.locale.value
}

export function definirIdioma(idioma: Idioma): void {
  i18n.global.locale.value = idioma
  document.documentElement.lang = idioma
  try {
    localStorage.setItem(CHAVE, idioma)
  } catch {
    // sem persistência: vale só nesta aba
  }
}

/** Compara textos na ordem alfabética do idioma atual (listas de pessoas, categorias). */
export function compararTexto(a: string, b: string): number {
  return a.localeCompare(b, idiomaAtual())
}
