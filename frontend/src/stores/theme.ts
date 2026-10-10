import { defineStore } from 'pinia'
import { ref, watchEffect } from 'vue'

export type Tema = 'claro' | 'escuro' | 'automatico'

const CHAVE = 'tf-tema'

function lerTema(): Tema {
  try {
    const salvo = localStorage.getItem(CHAVE)
    if (salvo === 'claro' || salvo === 'escuro' || salvo === 'automatico') return salvo
  } catch {
    // armazenamento indisponível (modo privado): usa o padrão
  }
  return 'automatico'
}

/**
 * Tema claro, escuro ou automático (docs/17 §17.4). Até existir o perfil do usuário
 * (Sprint 2), a escolha fica no navegador.
 */
export const useThemeStore = defineStore('tema', () => {
  const tema = ref<Tema>(lerTema())
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  const sistemaEscuro = ref(media.matches)
  media.addEventListener('change', (e) => (sistemaEscuro.value = e.matches))

  watchEffect(() => {
    const escuro = tema.value === 'escuro' || (tema.value === 'automatico' && sistemaEscuro.value)
    document.documentElement.classList.toggle('dark', escuro)
    try {
      localStorage.setItem(CHAVE, tema.value)
    } catch {
      // sem persistência: o tema vale só nesta aba
    }
  })

  return { tema }
})
