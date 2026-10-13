import { mount, type ComponentMountingOptions } from '@vue/test-utils'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'
import { expect, vi } from 'vitest'
import type { Component } from 'vue'

import { i18n } from '@/i18n'

// O jsdom não tem scrollIntoView, que a lista do Combobox (Reka UI) chama ao abrir.
Element.prototype.scrollIntoView ??= () => {}

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
  const feitas: {
    metodo: string
    caminho: string
    query: URLSearchParams
    corpo: unknown
    headers: Headers
  }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (req: Request) => {
      const url = new URL(req.url)
      const caminho = url.pathname
      const texto = await req.text()
      feitas.push({
        metodo: req.method,
        caminho,
        query: url.searchParams,
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

/** Escolhe uma opção de um Select (Reka UI) pelo teclado, como um usuário. */
export async function escolher(rotulo: string, opcao: string) {
  const label = [...document.querySelectorAll('label')].find((l) => l.textContent?.includes(rotulo))
  const trigger = document.getElementById(label!.htmlFor)!
  trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  const item = await vi.waitFor(() => {
    const encontrado = [...document.querySelectorAll('[role=option]')].find(
      (o) => o.textContent?.trim() === opcao,
    )
    expect(encontrado).toBeTruthy()
    return encontrado as HTMLElement
  })
  item.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await vi.waitFor(() => expect(document.querySelector('[role=listbox]')).toBeNull())
}
