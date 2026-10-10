import { mount, type ComponentMountingOptions } from '@vue/test-utils'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'
import { vi } from 'vitest'
import type { Component } from 'vue'

import { i18n } from '@/i18n'

/**
 * Monta um componente com os mesmos plugins da aplicação (router só se for passado).
 * O `queryClient` do teste fica junto do wrapper, para conferir o cache.
 */
export function montar<C extends Component>(
  componente: C,
  options: ComponentMountingOptions<C> = {},
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const pinia = createPinia()
  setActivePinia(pinia)
  const extras = options.global?.plugins ?? []
  const wrapper = mount(componente, {
    ...options,
    attachTo: document.body,
    global: {
      ...options.global,
      plugins: [pinia, i18n, [VueQueryPlugin, { queryClient }], ...extras],
      stubs: extras.length ? {} : { RouterLink: true },
    },
  } as ComponentMountingOptions<C>)
  return Object.assign(wrapper, { queryClient })
}

type Resposta = [status: number, corpo?: unknown]

/**
 * Simula a API: `rotas` mapeia "MÉTODO /caminho" para [status, corpo].
 * Devolve a lista de requisições feitas, para conferir o que foi enviado.
 */
export function simularApi(rotas: Record<string, Resposta | (() => Resposta)>) {
  const feitas: { metodo: string; caminho: string; corpo: unknown; headers: Headers }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (req: Request) => {
      const caminho = new URL(req.url).pathname
      const texto = await req.text()
      feitas.push({
        metodo: req.method,
        caminho,
        corpo: texto ? JSON.parse(texto) : undefined,
        headers: req.headers,
      })
      const definida = rotas[`${req.method} ${caminho}`]
      const [status, corpo] = typeof definida === 'function' ? definida() : (definida ?? [404, {}])
      return corpo === undefined
        ? new Response(null, { status })
        : new Response(JSON.stringify(corpo), {
            status,
            headers: { 'Content-Type': 'application/json' },
          })
    }),
  )
  return feitas
}

export const ME_ADMIN = {
  id: '00000000-0000-0000-0000-000000000001',
  email: 'admin@exemplo.com',
  username: null,
  full_name: 'Admin',
  must_change_password: false,
  role: 'admin',
  teams: [],
  permissions: ['admin.users', 'admin.organization', 'audit.view'],
  locale: null,
}

export const ME_AGENTE = { ...ME_ADMIN, role: 'agent', permissions: ['ticket.create'] }
