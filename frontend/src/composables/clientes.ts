import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { api, ou } from '@/api/client'

/** Clientes ativos para escolher (chamado, relatórios): só o id e o nome, aberto a todos. */
export function useOpcoesClientes(q: MaybeRefOrGetter<string>, ativa: MaybeRefOrGetter<boolean>) {
  return useQuery({
    queryKey: computed(() => ['clientes', 'opcoes', toValue(q)]),
    queryFn: async () =>
      ou(
        await api.GET('/api/v1/clients/options', {
          params: { query: { q: toValue(q).trim() || undefined } },
        }),
      ).items,
    placeholderData: keepPreviousData,
    enabled: computed(() => toValue(ativa)),
  })
}
