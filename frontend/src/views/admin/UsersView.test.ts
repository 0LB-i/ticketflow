import { afterEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import { escolher, ME_ADMIN, montar, simularApi } from '@/test/setup'

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
  display_name: 'Bruno',
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
      [campos[1], 'Bruno'],
      [campos[2], 'bruno@exemplo.com'],
      [campos[3], 'bruno'],
      [campos[4], 'Provisoria#2026'],
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
      display_name: 'Bruno',
      email: 'bruno@exemplo.com',
      username: 'bruno',
      role: 'agent',
      password: 'Provisoria#2026',
      team_ids: [GRUPO.id],
    })
    expect(criacao.headers.get('X-CSRF-Token')).toBe('token-csrf')
  })

  it('filtra por papel, grupo e situação', async () => {
    const outro = {
      ...USUARIO,
      id: '00000000-0000-0000-0000-000000000003',
      full_name: 'Carla Souza',
      display_name: 'Carla',
      role: 'admin',
      status: 'ativo',
      teams: [{ id: GRUPO.id, name: GRUPO.name }],
    }
    simularApi({
      'GET /api/v1/users': [200, { items: [USUARIO, outro] }],
      'GET /api/v1/teams': [200, { items: [GRUPO] }],
    })
    const w = montar(UsersView, { attachTo: document.body })
    useAuthStore().me = ME_ADMIN
    await vi.waitFor(() => expect(w.text()).toContain('Carla Souza'))
    expect(w.text()).toContain('Bruno Lima')

    await escolher('Papel', 'Agente')
    await vi.waitFor(() => expect(w.text()).not.toContain('Carla Souza'))
    expect(w.text()).toContain('Bruno Lima')

    await escolher('Papel', 'Todos os papéis')
    await escolher('Grupos', 'TI')
    await vi.waitFor(() => expect(w.text()).not.toContain('Bruno Lima'))
    expect(w.text()).toContain('Carla Souza')

    await escolher('Situação', 'Convite pendente')
    await vi.waitFor(() => expect(w.text()).not.toContain('Carla Souza'))
  })

  it('exclui depois de confirmar', async () => {
    document.cookie = 'tf_csrf=token-csrf'
    const feitas = simularApi({
      'GET /api/v1/users': [200, { items: [{ ...USUARIO, status: 'ativo' }] }],
      'GET /api/v1/teams': [200, { items: [] }],
      [`DELETE /api/v1/users/${USUARIO.id}`]: [204, undefined],
    })
    const w = montar(UsersView)
    useAuthStore().me = ME_ADMIN
    await vi.waitFor(() => expect(w.text()).toContain('Bruno Lima'))
    expect(w.findAll('button').some((b) => b.text() === 'Bruno')).toBe(true)
    expect(w.text()).not.toContain('Mostrar inativos')

    await w
      .findAll('button')
      .find((b) => b.text() === 'Bruno')!
      .trigger('click')
    const botao = (texto: string, onde: ParentNode = document.body) =>
      [...onde.querySelectorAll('button')].filter((b) => b.textContent?.trim() === texto)
    await vi.waitFor(() => expect(botao('Excluir usuário')).toHaveLength(1))
    expect(botao('Desativar')).toHaveLength(0)
    botao('Excluir usuário')[0]!.click()

    await vi.waitFor(() => expect(document.body.textContent).toContain('Excluir Bruno Lima?'))
    expect(feitas.some((r) => r.metodo === 'DELETE')).toBe(false)
    botao('Excluir usuário').at(-1)!.click()
    // Excluído (204, sem corpo): o painel fecha, sem mensagem de erro.
    await vi.waitFor(() => expect(document.body.querySelector('[role=dialog]')).toBeNull())
    expect(feitas.filter((r) => r.metodo === 'DELETE')).toHaveLength(1)
  })
})
