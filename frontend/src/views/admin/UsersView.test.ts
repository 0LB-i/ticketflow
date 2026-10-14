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
  username: null,
  full_name: 'Bruno Lima',
  role: 'agent',
  status: 'convite_pendente',
  teams: [],
  last_login_at: null,
  created_at: '2026-10-10T10:00:00Z',
}

const GRUPO = {
  id: '00000000-0000-0000-0000-0000000000a1',
  name: 'TI',
  description: null,
  notify_on_new: 'queue_only',
  is_active: true,
  members: [],
}

describe('UsersView', () => {
  it('cria com a senha inicial e já como membro do grupo marcado', async () => {
    document.cookie = 'tf_csrf=token-csrf'
    const feitas = simularApi({
      'GET /api/v1/users': [200, { items: [] }],
      'GET /api/v1/teams': [
        200,
        { items: [GRUPO, { ...GRUPO, id: 'x', name: 'Antigo', is_active: false }] },
      ],
      'POST /api/v1/users': [201, { ...USUARIO, status: 'ativo' }],
    })
    const w = montar(UsersView)
    useAuthStore().me = ME_ADMIN
    await vi.waitFor(() => expect(w.text()).toContain('Nenhum registro'))

    await w.get('button').trigger('click') // "Novo usuário"
    const painel = () => document.body.querySelector('[role=dialog]')!
    await vi.waitFor(() => expect(painel()?.textContent).toContain('TI'))
    expect(painel().textContent).not.toContain('Antigo')
    const campos = painel().querySelectorAll<HTMLInputElement>('input:not([type=checkbox])')
    for (const [campo, valor] of [
      [campos[0], 'Bruno Lima'],
      [campos[1], 'bruno@exemplo.com'],
      [campos[2], 'Provisoria#2026'],
    ] as const) {
      campo!.value = valor
      campo!.dispatchEvent(new Event('input'))
    }
    painel().querySelector<HTMLInputElement>('input[type=checkbox]')!.click()
    painel().querySelector('form')!.dispatchEvent(new Event('submit'))

    await vi.waitFor(() => expect(feitas.find((r) => r.metodo === 'POST')).toBeDefined())
    const criacao = feitas.find((r) => r.metodo === 'POST')!
    expect(criacao.corpo).toEqual({
      full_name: 'Bruno Lima',
      email: 'bruno@exemplo.com',
      role: 'agent',
      password: 'Provisoria#2026',
      team_ids: [GRUPO.id],
    })
    expect(criacao.headers.get('X-CSRF-Token')).toBe('token-csrf')
  })
})
