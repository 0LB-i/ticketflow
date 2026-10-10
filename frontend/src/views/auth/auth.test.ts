import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { criarRouter } from '@/router'
import { ME_AGENTE, montar, simularApi } from '@/test/setup'

import LoginView from './LoginView.vue'
import SetPasswordView from './SetPasswordView.vue'

let router: ReturnType<typeof criarRouter>

beforeEach(() => {
  setActivePinia(createPinia())
  router = criarRouter()
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('LoginView', () => {
  it('entra e volta para a página que tinha sido pedida', async () => {
    let logado = false
    const feitas = simularApi({
      'GET /api/v1/me': () => (logado ? [200, ME_AGENTE] : [401, { status: 401 }]),
      'POST /api/v1/auth/login': () => {
        logado = true
        return [204]
      },
    })
    await router.push('/login?volta=/dev/componentes')
    const w = montar(LoginView, { global: { plugins: [router] } })
    await w.get('input[type=email]').setValue('ana@exemplo.com')
    await w.get('input[type=password]').setValue('uma senha longa de teste')
    await w.get('form').trigger('submit')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/dev/componentes'))
    expect(feitas.find((r) => r.caminho === '/api/v1/auth/login')?.corpo).toEqual({
      email: 'ana@exemplo.com',
      password: 'uma senha longa de teste',
    })
  })

  it('mostra o erro genérico da API', async () => {
    simularApi({
      'GET /api/v1/me': [401, { status: 401 }],
      'POST /api/v1/auth/login': [401, { status: 401, detail: 'E-mail ou senha inválidos.' }],
    })
    await router.push('/login')
    const w = montar(LoginView, { global: { plugins: [router] } })
    await w.get('input[type=email]').setValue('ana@exemplo.com')
    await w.get('input[type=password]').setValue('errada errada')
    await w.get('form').trigger('submit')
    await vi.waitFor(() => expect(w.get('[role=alert]').text()).toBe('E-mail ou senha inválidos.'))
  })
})

describe('SetPasswordView', () => {
  it('link inválido oferece pedir outro', async () => {
    simularApi({ 'GET /api/v1/auth/tokens/velho': [404, { status: 404 }] })
    const w = montar(SetPasswordView, {
      props: { token: 'velho', tipo: 'redefinir' },
      global: { plugins: [router] },
    })
    await vi.waitFor(() => expect(w.text()).toContain('inválido ou expirou'))
    expect(w.text()).toContain('Pedir um link novo')
  })

  it('cria a senha do convite e vai para o login', async () => {
    const feitas = simularApi({
      'GET /api/v1/me': [401, { status: 401 }],
      'GET /api/v1/auth/tokens/bom': [
        200,
        { purpose: 'invite', email: 'bruno@exemplo.com', full_name: 'Bruno Lima' },
      ],
      'POST /api/v1/auth/invite/accept': [204],
    })
    await router.push('/convite/bom')
    const w = montar(SetPasswordView, {
      props: { token: 'bom', tipo: 'convite' },
      global: { plugins: [router] },
    })
    await vi.waitFor(() => expect(w.text()).toContain('Bruno Lima'))
    const [senha, confirmar] = w.findAll('input[type=password]')
    await senha!.setValue('cavalo bateria grampo')
    await confirmar!.setValue('cavalo bateria grampo')
    await w.get('form').trigger('submit')
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('login'))
    expect(feitas.find((r) => r.metodo === 'POST')?.corpo).toEqual({
      token: 'bom',
      password: 'cavalo bateria grampo',
    })
  })
})
