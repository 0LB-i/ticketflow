import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, type Schemas } from '@/api/client'
import { folhaDeEstilo, paleta } from '@/tema/paleta'

export type Branding = Schemas['Branding']

const CHAVE_CORES = 'tf-cores'

/**
 * Aplica as cores personalizadas por cima dos tokens do main.css. A folha também fica no
 * navegador, para o public/tema.js aplicá-la antes da primeira pintura no próximo acesso.
 */
export function aplicarCores(cores: Branding['colors']): void {
  const css = cores ? folhaDeEstilo(paleta(cores)) : ''
  let estilo = document.getElementById('tf-cores')
  if (css && !estilo) {
    estilo = document.createElement('style')
    estilo.id = 'tf-cores'
    document.head.appendChild(estilo)
  }
  if (estilo) estilo.textContent = css
  try {
    if (css) localStorage.setItem(CHAVE_CORES, css)
    else localStorage.removeItem(CHAVE_CORES)
  } catch {
    // sem persistência: as cores chegam com o /branding
  }
}

/** Identidade visual da instalação (configurações): idioma padrão, cores e logotipo. */
export const useBrandingStore = defineStore('branding', () => {
  const dados = ref<Branding | null>(null)
  const idiomaPadrao = computed(() => dados.value?.default_locale ?? 'pt-BR')

  function aplicar(branding: Branding): void {
    dados.value = branding
    aplicarCores(branding.colors)
  }

  async function carregar(): Promise<void> {
    const { data } = await api.GET('/api/v1/branding')
    if (data) aplicar(data)
  }

  return { dados, idiomaPadrao, aplicar, carregar }
})
