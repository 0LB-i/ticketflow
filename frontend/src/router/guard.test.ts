import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ME_ADMIN, ME_AGENTE, simularApi } from '@/test/setup'

import { criarRouter } from './index'

let router: ReturnType<typeof criarRouter>

describe('proteção das rotas (docs/13 §13.3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    router = criarRouter()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('sem sessão manda para o login e guarda a página pedida', async () => {
    simularApi({ 'GET /api/v1/me': [401, { status: 401 }] })
    await router.push('/admin/usuarios')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.volta).toBe('/admin/usuarios')
  })

  it('a tela inicial é a lista de chamados', async () => {
    simularApi({ 'GET /api/v1/me': [200, ME_AGENTE] })
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('chamados')
  })

  it('sem sessão, a tela inicial vai para o login sem "volta"', async () => {
    simularApi({ 'GET /api/v1/me': [401, { status: 401 }] })
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query).toEqual({})
  })

  it('sem a permissão da tela mostra "sem acesso"', async () => {
    simularApi({ 'GET /api/v1/me': [200, ME_AGENTE] })
    await router.push('/admin/grupos')
    expect(router.currentRoute.value.name).toBe('sem-acesso')
  })

  it('registrar chamado exige ticket.create (o auditor não registra)', async () => {
    simularApi({ 'GET /api/v1/me': [200, { ...ME_AGENTE, role: 'auditor', permissions: [] }] })
    await router.push('/chamados/novo')
    expect(router.currentRoute.value.name).toBe('sem-acesso')
    await router.push('/chamados/1234')
    expect(router.currentRoute.value.name).toBe('chamado')
  })

  it('quem já está logado não vê a tela de login', async () => {
    simularApi({ 'GET /api/v1/me': [200, ME_AGENTE] })
    await router.push('/login')
    expect(router.currentRoute.value.name).toBe('chamados')
  })

  it('com barra final ou maiúsculas, as telas do servidor não recarregam a página', async () => {
    simularApi({ 'GET /api/v1/me': [200, ME_AGENTE] })
    await router.push('/chamados/')
    expect(router.currentRoute.value.name).toBe('nao-encontrado')
    await router.push('/Chamados')
    expect(router.currentRoute.value.name).toBe('nao-encontrado')
  })

  it('convite continua acessível mesmo logado', async () => {
    simularApi({ 'GET /api/v1/me': [200, ME_AGENTE] })
    await router.push('/convite/abc')
    expect(router.currentRoute.value.name).toBe('convite')
  })
})

describe('senha provisória (docs/09 §9.2)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    router = criarRouter()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('com senha provisória, qualquer tela leva à troca de senha', async () => {
    simularApi({
      'GET /api/v1/me': [
        200,
        { ...ME_ADMIN, username: 'admin', email: null, must_change_password: true },
      ],
    })
    await router.push('/admin/usuarios')
    expect(router.currentRoute.value.name).toBe('trocar-senha')
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('trocar-senha')
  })

  it('depois da troca, a tela de troca obrigatória não abre mais', async () => {
    simularApi({ 'GET /api/v1/me': [200, ME_ADMIN] })
    await router.push('/trocar-senha')
    expect(router.currentRoute.value.name).toBe('chamados')
  })
})
