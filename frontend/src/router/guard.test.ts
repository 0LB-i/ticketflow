import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ME_AGENTE, simularApi } from '@/test/setup'

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

  it('sem a permissão da tela mostra "sem acesso"', async () => {
    simularApi({ 'GET /api/v1/me': [200, ME_AGENTE] })
    await router.push('/admin/grupos')
    expect(router.currentRoute.value.name).toBe('sem-acesso')
  })

  it('quem já está logado não vê a tela de login', async () => {
    simularApi({ 'GET /api/v1/me': [200, ME_AGENTE] })
    await router.push('/login')
    expect(router.currentRoute.value.name).toBe('inicio')
  })

  it('convite continua acessível mesmo logado', async () => {
    simularApi({ 'GET /api/v1/me': [200, ME_AGENTE] })
    await router.push('/convite/abc')
    expect(router.currentRoute.value.name).toBe('convite')
  })
})
