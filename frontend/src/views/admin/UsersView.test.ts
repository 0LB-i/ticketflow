import { afterEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import { ME_ADMIN, montar, simularApi } from '@/test/setup'

import UsersView from './UsersView.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const USUARIO = {
  id: '00000000-0000-0000-0000-000000000002',
  email: 'bruno@exemplo.com',
  full_name: 'Bruno Lima',
  role: 'agent',
  status: 'convite_pendente',
  teams: [],
  last_login_at: null,
  created_at: '2026-10-10T10:00:00Z',
}

describe('UsersView', () => {
  it('sem SMTP, mostra o link de convite para copiar', async () => {
    document.cookie = 'tf_csrf=token-csrf'
    const feitas = simularApi({
      'GET /api/v1/users': [200, { items: [] }],
      'POST /api/v1/users': [
        201,
        {
          ...USUARIO,
          link: { purpose: 'invite', sent_by_email: false, url: 'http://ticketflow/convite/xyz' },
        },
      ],
    })
    const w = montar(UsersView)
    useAuthStore().me = ME_ADMIN
    await vi.waitFor(() => expect(w.text()).toContain('Nenhum registro'))

    await w.get('button').trigger('click') // "Novo usuário"
    const painel = () => document.body.querySelector('[role=dialog]')!
    await vi.waitFor(() => expect(painel()).not.toBeNull())
    const campos = painel().querySelectorAll('input')
    for (const [campo, valor] of [
      [campos[0], 'Bruno Lima'],
      [campos[1], 'bruno@exemplo.com'],
    ] as const) {
      campo!.value = valor
      campo!.dispatchEvent(new Event('input'))
    }
    painel().querySelector('form')!.dispatchEvent(new Event('submit'))

    await vi.waitFor(() =>
      expect(document.body.querySelector<HTMLInputElement>('input[readonly]')?.value).toBe(
        'http://ticketflow/convite/xyz',
      ),
    )
    const criacao = feitas.find((r) => r.metodo === 'POST')!
    expect(criacao.corpo).toEqual({
      full_name: 'Bruno Lima',
      email: 'bruno@exemplo.com',
      role: 'agent',
    })
    expect(criacao.headers.get('X-CSRF-Token')).toBe('token-csrf')
  })
})
