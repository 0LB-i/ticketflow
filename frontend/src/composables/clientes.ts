import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { api, ou, type Schemas } from '@/api/client'

export type Cliente = Schemas['ClientOut']
export type ClienteEntrada = Schemas['ClientIn']
export type TipoCliente = Cliente['kind']

/** Lista paginada pela API, com a busca e os inativos como filtros. */
export function useClientes(
  filtro: MaybeRefOrGetter<{ q: string; inativos: boolean }>,
  ativa: MaybeRefOrGetter<boolean> = true,
) {
  return useQuery({
    queryKey: computed(() => ['clientes', toValue(filtro)]),
    queryFn: async () => {
      const { q, inativos } = toValue(filtro)
      return ou(
        await api.GET('/api/v1/clients', {
          params: { query: { q: q.trim() || undefined, inactive: inativos, limit: 200 } },
        }),
      )
    },
    placeholderData: keepPreviousData,
    enabled: computed(() => toValue(ativa)),
  })
}

export function useCliente(id: MaybeRefOrGetter<string | null>) {
  return useQuery({
    queryKey: computed(() => ['cliente', toValue(id)]),
    queryFn: async () =>
      ou(
        await api.GET('/api/v1/clients/{client_id}', {
          params: { path: { client_id: toValue(id)! } },
        }),
      ),
    enabled: computed(() => toValue(id) !== null),
  })
}

export const clientesApi = {
  criar: async (body: ClienteEntrada) => ou(await api.POST('/api/v1/clients', { body })),
  editar: async ({ id, ...body }: ClienteEntrada & { id: string }) =>
    ou(await api.PUT('/api/v1/clients/{client_id}', { params: { path: { client_id: id } }, body })),
}
