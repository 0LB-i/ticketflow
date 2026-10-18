import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { api, erroInesperado, mensagemDeErro, ou, type Schemas } from '@/api/client'
import { compararTexto } from '@/i18n'
import type { Pessoa } from '@/components/editor/MentionList.vue'

import { useGrupos } from './admin'

export type Chamado = Schemas['TicketOut']
export type Comentario = Schemas['CommentOut']
export type Acao = Schemas['TransitionIn']['action']

const caminho = (numero: string | number) => ({ path: { ticket_ref: String(numero) } })

/** Os status na ordem definida em Configurações. */
export function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: async () => ou(await api.GET('/api/v1/statuses')).items,
    staleTime: Infinity,
  })
}

/** Colegas ativos de todos os grupos, para menções, observadores e responsável. */
export function usePessoas() {
  const grupos = useGrupos()
  return computed<Pessoa[]>(() => {
    const vistos = new Map<string, Pessoa>()
    for (const g of grupos.data.value ?? []) {
      for (const m of g.members) {
        if (m.is_active) vistos.set(m.user_id, { id: m.user_id, label: m.display_name })
      }
    }
    return [...vistos.values()].sort((a, b) => compararTexto(a.label, b.label))
  })
}

/** Detalhe do chamado. O erro guarda o status HTTP (403 e 404 têm telas próprias). */
export function useChamado(numero: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => ['chamado', toValue(numero)]),
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/tickets/{ticket_ref}', {
        params: caminho(toValue(numero)),
      })
      if (error !== undefined || !data)
        throw Object.assign(new Error(erroInesperado()), { status: response.status })
      return data
    },
    retry: false,
  })
}

export function useComentarios(numero: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => ['chamado', toValue(numero), 'comentarios']),
    queryFn: async () =>
      ou(
        await api.GET('/api/v1/tickets/{ticket_ref}/comments', {
          params: caminho(toValue(numero)),
        }),
      ).items,
  })
}

/** Mesmo status em vários chamados (supervisor ou admin): recarrega as listas e os detalhes. */
/** Ação num chamado: ao terminar, recarrega o detalhe, os comentários e a lista. */
export function useAcaoNoChamado<A, R>(numero: MaybeRefOrGetter<string>, fn: (a: A) => Promise<R>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ['chamado', toValue(numero)] }),
        client.invalidateQueries({ queryKey: ['chamados'] }),
      ]),
  })
}

export const chamadosApi = {
  registrar: async (body: Schemas['TicketCreate']) =>
    ou(await api.POST('/api/v1/tickets', { body })),
  comentar: async (numero: string, body: Schemas['CommentIn']) =>
    ou(await api.POST('/api/v1/tickets/{ticket_ref}/comments', { params: caminho(numero), body })),
  editarComentario: async (numero: string, id: string, body: Schemas['CommentIn']) =>
    ou(
      await api.PATCH('/api/v1/tickets/{ticket_ref}/comments/{comment_id}', {
        params: { path: { ticket_ref: numero, comment_id: id } },
        body,
      }),
    ),
  atribuir: async (numero: string, assignee: string) =>
    ou(
      await api.POST('/api/v1/tickets/{ticket_ref}/assign', {
        params: caminho(numero),
        body: { assignee },
      }),
    ),
  transferir: async (numero: string, body: Schemas['TransferIn']) =>
    ou(await api.POST('/api/v1/tickets/{ticket_ref}/transfer', { params: caminho(numero), body })),
  /** Qualquer status, sem as exigências do fluxo (ação set_status). */
  mudarStatusPara: async (numero: string, status_id: number) =>
    ou(
      await api.PATCH('/api/v1/tickets/{ticket_ref}', {
        params: caminho(numero),
        body: { status_id },
      }),
    ),
  /** Cliente do chamado (obrigatório: troca, mas não tira). */
  trocarCliente: async (numero: string, client_id: string) =>
    ou(
      await api.PATCH('/api/v1/tickets/{ticket_ref}', {
        params: caminho(numero),
        body: { client_id },
      }),
    ),
  removerComentario: async (numero: string, id: string) => {
    const r = await api.DELETE('/api/v1/tickets/{ticket_ref}/comments/{comment_id}', {
      params: { path: { ticket_ref: numero, comment_id: id } },
    })
    if (r.error !== undefined) throw new Error(mensagemDeErro(r.error))
  },
  mudarStatus: async (numero: string, body: Schemas['TransitionIn']) =>
    ou(
      await api.POST('/api/v1/tickets/{ticket_ref}/transitions', { params: caminho(numero), body }),
    ),
  observar: async (numero: string, usuario: string, observar: boolean) => {
    const params = { path: { ticket_ref: numero, user_id: usuario } }
    const r = observar
      ? await api.PUT('/api/v1/tickets/{ticket_ref}/watchers/{user_id}', { params })
      : await api.DELETE('/api/v1/tickets/{ticket_ref}/watchers/{user_id}', { params })
    if (r.error !== undefined) throw new Error(mensagemDeErro(r.error))
  },
}
