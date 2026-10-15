import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { api, ou, type Schemas } from '@/api/client'

export type Cliente = Schemas['ClientOut']
export type ClienteEntrada = Schemas['ClientIn']
export type TipoCliente = Cliente['kind']

/** Lista paginada pela API, com a busca, o tipo, a UF e os inativos como filtros. */
export function useClientes(
  filtro: MaybeRefOrGetter<{
    q: string
    inativos: boolean
    tipo: TipoCliente | null
    uf: string | null
  }>,
  ativa: MaybeRefOrGetter<boolean> = true,
) {
  return useQuery({
    queryKey: computed(() => ['clientes', toValue(filtro)]),
    queryFn: async () => {
      const { q, inativos, tipo, uf } = toValue(filtro)
      return ou(
        await api.GET('/api/v1/clients', {
          params: {
            query: {
              q: q.trim() || undefined,
              inactive: inativos,
              kind: tipo ?? undefined,
              state: uf ?? undefined,
              limit: 200,
            },
          },
        }),
      )
    },
    placeholderData: keepPreviousData,
    enabled: computed(() => toValue(ativa)),
  })
}

/** Clientes ativos para escolher (chamado, relatórios): só o id e o nome, aberto a todos.
 * Relidos a cada abertura da lista: um cliente cadastrado em outra sessão já aparece. */
export function useOpcoesClientes(q: MaybeRefOrGetter<string>, ativa: MaybeRefOrGetter<boolean>) {
  return useQuery({
    queryKey: computed(() => ['clientes', 'opcoes', toValue(q)]),
    queryFn: async () =>
      ou(
        await api.GET('/api/v1/clients/options', {
          params: { query: { q: toValue(q).trim() || undefined } },
        }),
      ).items,
    staleTime: 0,
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
