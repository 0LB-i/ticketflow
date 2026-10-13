import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { api, mensagemDeErro, ou, type Schemas } from '@/api/client'
import type { operations } from '@/api/schema'
import { compararTexto, i18n } from '@/i18n'
import type { Pessoa } from '@/components/editor/MentionList.vue'

import { useGrupos } from './admin'

export type Chamado = Schemas['TicketOut']
export type ItemDaLista = Schemas['TicketListItem']
/** Fila e filtros da lista, como a API recebe (sem o cursor). */
export type FiltroChamados = Omit<
  NonNullable<operations['list_tickets_api_v1_tickets_get']['parameters']['query']>,
  'cursor' | 'limit'
>
export type Fila = NonNullable<FiltroChamados['view']>
export type Comentario = Schemas['CommentOut']
export type Evento = Schemas['EventOut']
export type Acao = Schemas['TransitionIn']['action']
export type TipoChamado = Schemas['TicketCreate']['type'] & string

const erro = () => i18n.global.t('comum.erroInesperado')
const caminho = (numero: string | number) => ({ path: { ticket_ref: String(numero) } })

/** Os status na ordem definida em Configurações. */
export function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: async () => ou(await api.GET('/api/v1/statuses'), erro()).items,
    staleTime: Infinity,
  })
}

export function useCodigosDeResolucao() {
  return useQuery({
    queryKey: ['codigos-resolucao'],
    queryFn: async () => ou(await api.GET('/api/v1/resolution-codes'), erro()).items,
  })
}

/** Colegas ativos de todos os grupos, para menções, observadores e responsável. */
export function usePessoas() {
  const grupos = useGrupos()
  return computed<Pessoa[]>(() => {
    const vistos = new Map<string, Pessoa>()
    for (const g of grupos.data.value ?? []) {
      for (const m of g.members) {
        if (m.is_active) vistos.set(m.user_id, { id: m.user_id, label: m.full_name })
      }
    }
    return [...vistos.values()].sort((a, b) => compararTexto(a.label, b.label))
  })
}

/** Uma fila da lista com os filtros. As chaves começam por 'chamados': toda ação as recarrega. */
export function useChamados(filtro: MaybeRefOrGetter<FiltroChamados>) {
  return useInfiniteQuery({
    queryKey: computed(() => ['chamados', toValue(filtro)]),
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      ou(
        await api.GET('/api/v1/tickets', {
          params: { query: { ...toValue(filtro), cursor: pageParam } },
        }),
        erro(),
      ),
    getNextPageParam: (pagina) => pagina.next_cursor,
  })
}

/** Quantos chamados há em cada fila (as abas). */
export function useContagens() {
  return useQuery({
    queryKey: ['chamados', 'contagens'],
    queryFn: async () => ou(await api.GET('/api/v1/tickets/counts'), erro()),
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
        throw Object.assign(new Error(erro()), { status: response.status })
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
        erro(),
      ).items,
  })
}

export function useEventos(numero: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => ['chamado', toValue(numero), 'eventos']),
    queryFn: async () =>
      ou(
        await api.GET('/api/v1/tickets/{ticket_ref}/events', { params: caminho(toValue(numero)) }),
        erro(),
      ).items,
  })
}

/** Ação num chamado: ao terminar, recarrega o detalhe, os comentários, o histórico e a lista. */
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
  pegarProximo: async (team_id: string | null) =>
    ou(await api.POST('/api/v1/tickets/next', { body: { team_id } }), erro()),
  registrar: async (body: Schemas['TicketCreate']) =>
    ou(await api.POST('/api/v1/tickets', { body }), erro()),
  editar: async (numero: string, body: Schemas['TicketUpdate']) =>
    ou(await api.PATCH('/api/v1/tickets/{ticket_ref}', { params: caminho(numero), body }), erro()),
  comentar: async (numero: string, body: Schemas['CommentIn']) =>
    ou(
      await api.POST('/api/v1/tickets/{ticket_ref}/comments', { params: caminho(numero), body }),
      erro(),
    ),
  editarComentario: async (numero: string, id: string, body: Schemas['CommentIn']) =>
    ou(
      await api.PATCH('/api/v1/tickets/{ticket_ref}/comments/{comment_id}', {
        params: { path: { ticket_ref: numero, comment_id: id } },
        body,
      }),
      erro(),
    ),
  atribuir: async (numero: string, assignee: string | null) =>
    ou(
      await api.POST('/api/v1/tickets/{ticket_ref}/assign', {
        params: caminho(numero),
        body: { assignee },
      }),
      erro(),
    ),
  transferir: async (numero: string, body: Schemas['TransferIn']) =>
    ou(
      await api.POST('/api/v1/tickets/{ticket_ref}/transfer', { params: caminho(numero), body }),
      erro(),
    ),
  mudarStatus: async (numero: string, body: Schemas['TransitionIn']) =>
    ou(
      await api.POST('/api/v1/tickets/{ticket_ref}/transitions', { params: caminho(numero), body }),
      erro(),
    ),
  observar: async (numero: string, usuario: string, observar: boolean) => {
    const params = { path: { ticket_ref: numero, user_id: usuario } }
    const r = observar
      ? await api.PUT('/api/v1/tickets/{ticket_ref}/watchers/{user_id}', { params })
      : await api.DELETE('/api/v1/tickets/{ticket_ref}/watchers/{user_id}', { params })
    if (r.error !== undefined) throw new Error(mensagemDeErro(r.error, erro()))
  },
}
