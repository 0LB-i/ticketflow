import { useMutation, useQueryClient } from '@tanstack/vue-query'

import { api, ou, type Schemas } from '@/api/client'
import { i18n } from '@/i18n'

const erro = () => i18n.global.t('comum.erroInesperado')

/** Mutação que, ao terminar, recarrega as listas indicadas. */
export function useAlteracao<A, R>(fn: (args: A) => Promise<R>, recarregar: string[]) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () =>
      Promise.all(recarregar.map((k) => client.invalidateQueries({ queryKey: [k] }))),
  })
}

/** Status dos chamados (Configurações). Cada chamada devolve a lista inteira, já na ordem. */
export const statusApi = {
  criar: async (body: Schemas['StatusCreate']) =>
    ou(await api.POST('/api/v1/statuses', { body }), erro()),
  renomear: async (a: { id: number; name: string }) =>
    ou(
      await api.PATCH('/api/v1/statuses/{status_id}', {
        params: { path: { status_id: a.id } },
        body: { name: a.name },
      }),
      erro(),
    ),
  ordenar: async (ids: number[]) =>
    ou(await api.PUT('/api/v1/statuses/order', { body: { ids } }), erro()),
  remover: async (id: number) =>
    ou(
      await api.DELETE('/api/v1/statuses/{status_id}', { params: { path: { status_id: id } } }),
      erro(),
    ),
}
