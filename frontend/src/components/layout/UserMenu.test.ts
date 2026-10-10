import { afterEach, describe, expect, it, vi } from 'vitest'

import { definirIdioma } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { ME_ADMIN, montar, simularApi } from '@/test/setup'

import UserMenu from './UserMenu.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
  definirIdioma('pt-BR')
})

describe('UserMenu', () => {
  it('escolhe o idioma da pessoa', async () => {
    const feitas = simularApi({ 'PATCH /api/v1/me': [200, { ...ME_ADMIN, locale: 'en' }] })
    const w = montar(UserMenu)
    useAuthStore().me = { ...ME_ADMIN }
    await vi.waitFor(() => expect(w.find('button').exists()).toBe(true))

    w.get('button').element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
    )
    const opcao = await vi.waitFor(() => {
      const item = [...document.querySelectorAll('[role=menuitemradio]')].find(
        (o) => o.textContent?.trim() === 'English',
      )
      expect(item).toBeTruthy()
      return item as HTMLElement
    })
    expect(document.body.textContent).toContain('Padrão do sistema (Português (Brasil))')
    opcao.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))

    await vi.waitFor(() =>
      expect(feitas.find((r) => r.metodo === 'PATCH')?.corpo).toEqual({ locale: 'en' }),
    )
    await vi.waitFor(() => expect(useAuthStore().me?.locale).toBe('en'))
  })
})
