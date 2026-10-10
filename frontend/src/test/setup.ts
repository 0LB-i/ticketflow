import { mount, type ComponentMountingOptions } from '@vue/test-utils'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import type { Component } from 'vue'

import { i18n } from '@/i18n'

/** Monta um componente com os mesmos plugins da aplicação. */
export function montar<C extends Component>(
  componente: C,
  options: ComponentMountingOptions<C> = {},
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(componente, {
    ...options,
    global: {
      plugins: [createPinia(), i18n, [VueQueryPlugin, { queryClient }]],
      stubs: { RouterLink: true },
      ...options.global,
    },
  } as ComponentMountingOptions<C>)
}
