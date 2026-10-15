import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api, mensagemDeErro, ou, type Schemas } from '@/api/client'
import { i18n } from '@/i18n'

export type Usuario = Schemas['UserOut']
export type Grupo = Schemas['TeamOut']
export type Setor = Schemas['DepartmentOut']
export type LinkDeAcesso = Schemas['LinkOut']

const erro = () => i18n.global.t('comum.erroInesperado')

export function useUsuarios() {
  return useQuery({
    queryKey: ['usuarios'],
    queryFn: async () => ou(await api.GET('/api/v1/users'), erro()).items,
  })
}

/** Grupos e membros. Sempre relidos ao abrir uma tela e ao voltar à aba: os formulários de
 * chamado dependem deles, e o admin pode tê-los mudado em outra sessão. */
export function useGrupos() {
  return useQuery({
    queryKey: ['grupos'],
    queryFn: async () => ou(await api.GET('/api/v1/teams'), erro()).items,
    staleTime: 0,
  })
}

export function useSetores() {
  return useQuery({
    queryKey: ['setores'],
    queryFn: async () => ou(await api.GET('/api/v1/departments'), erro()).items,
  })
}

/** Mutação que, ao terminar, recarrega as listas indicadas. */
export function useAlteracao<A, R>(fn: (args: A) => Promise<R>, recarregar: string[]) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () =>
      Promise.all(recarregar.map((k) => client.invalidateQueries({ queryKey: [k] }))),
  })
}

export const usuariosApi = {
  criar: async (body: Schemas['UserCreate']) =>
    ou(await api.POST('/api/v1/users', { body }), erro()),
  editar: async ({ id, ...body }: Schemas['UserUpdate'] & { id: string }) =>
    ou(
      await api.PATCH('/api/v1/users/{user_id}', { params: { path: { user_id: id } }, body }),
      erro(),
    ),
  enviarLink: async (id: string) =>
    ou(
      await api.POST('/api/v1/users/{user_id}/link', { params: { path: { user_id: id } } }),
      erro(),
    ),
  excluir: async (id: string) => {
    const r = await api.DELETE('/api/v1/users/{user_id}', { params: { path: { user_id: id } } })
    if (r.error !== undefined) throw new Error(mensagemDeErro(r.error, erro()))
  },
}

export const gruposApi = {
  criar: async (body: Schemas['TeamCreate']) =>
    ou(await api.POST('/api/v1/teams', { body }), erro()),
  editar: async ({ id, ...body }: Schemas['TeamUpdate'] & { id: string }) =>
    ou(
      await api.PATCH('/api/v1/teams/{team_id}', { params: { path: { team_id: id } }, body }),
      erro(),
    ),
  definirMembro: async (a: { grupo: string; usuario: string; role: 'member' | 'supervisor' }) =>
    ou(
      await api.PUT('/api/v1/teams/{team_id}/members/{user_id}', {
        params: { path: { team_id: a.grupo, user_id: a.usuario } },
        body: { role: a.role },
      }),
      erro(),
    ),
  removerMembro: async (a: { grupo: string; usuario: string }) =>
    ou(
      await api.DELETE('/api/v1/teams/{team_id}/members/{user_id}', {
        params: { path: { team_id: a.grupo, user_id: a.usuario } },
      }),
      erro(),
    ),
}

export const setoresApi = {
  criar: async (body: Schemas['DepartmentCreate']) =>
    ou(await api.POST('/api/v1/departments', { body }), erro()),
  editar: async ({ id, ...body }: Schemas['DepartmentUpdate'] & { id: string }) =>
    ou(
      await api.PATCH('/api/v1/departments/{dept_id}', { params: { path: { dept_id: id } }, body }),
      erro(),
    ),
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
