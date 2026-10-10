import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import { useThemeStore } from './theme'

function sistemaEscuro(escuro: boolean) {
  vi.stubGlobal('matchMedia', () => ({ matches: escuro, addEventListener: () => {} }))
}

describe('tema', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.className = ''
    setActivePinia(createPinia())
  })

  it('automático segue o sistema operacional', () => {
    sistemaEscuro(true)
    useThemeStore()
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('a escolha do usuário vence o sistema e fica salva', async () => {
    sistemaEscuro(true)
    const store = useThemeStore()
    store.tema = 'claro'
    await nextTick()
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem('tf-tema')).toBe('claro')
  })
})
