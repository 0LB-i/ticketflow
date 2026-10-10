import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { api, ou, type Schemas } from '@/api/client'

export type Usuario = Schemas['UserOut']
export type Grupo = Schemas['TeamOut']
export type Setor = Schemas['DepartmentOut']
export type LinkDeAcesso = Schemas['LinkOut']

const ERRO = 'Algo deu errado. Tente de novo.'

export function useUsuarios() {
  return useQuery({
    queryKey: ['usuarios'],
    queryFn: async () => ou(await api.GET('/api/v1/users'), ERRO).items,
  })
}

export function useGrupos() {
  return useQuery({
    queryKey: ['grupos'],
    queryFn: async () => ou(await api.GET('/api/v1/teams'), ERRO).items,
  })
}

export function useSetores() {
  return useQuery({
    queryKey: ['setores'],
    queryFn: async () => ou(await api.GET('/api/v1/departments'), ERRO).items,
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
  criar: async (body: Schemas['UserCreate']) => ou(await api.POST('/api/v1/users', { body }), ERRO),
  editar: async ({ id, ...body }: Schemas['UserUpdate'] & { id: string }) =>
    ou(
      await api.PATCH('/api/v1/users/{user_id}', { params: { path: { user_id: id } }, body }),
      ERRO,
    ),
  enviarLink: async (id: string) =>
    ou(await api.POST('/api/v1/users/{user_id}/link', { params: { path: { user_id: id } } }), ERRO),
}

export const gruposApi = {
  criar: async (body: Schemas['TeamCreate']) => ou(await api.POST('/api/v1/teams', { body }), ERRO),
  editar: async ({ id, ...body }: Schemas['TeamUpdate'] & { id: string }) =>
    ou(
      await api.PATCH('/api/v1/teams/{team_id}', { params: { path: { team_id: id } }, body }),
      ERRO,
    ),
  definirMembro: async (a: { grupo: string; usuario: string; role: 'member' | 'supervisor' }) =>
    ou(
      await api.PUT('/api/v1/teams/{team_id}/members/{user_id}', {
        params: { path: { team_id: a.grupo, user_id: a.usuario } },
        body: { role: a.role },
      }),
      ERRO,
    ),
  removerMembro: async (a: { grupo: string; usuario: string }) =>
    ou(
      await api.DELETE('/api/v1/teams/{team_id}/members/{user_id}', {
        params: { path: { team_id: a.grupo, user_id: a.usuario } },
      }),
      ERRO,
    ),
}

export const setoresApi = {
  criar: async (body: Schemas['DepartmentCreate']) =>
    ou(await api.POST('/api/v1/departments', { body }), ERRO),
  editar: async ({ id, ...body }: Schemas['DepartmentUpdate'] & { id: string }) =>
    ou(
      await api.PATCH('/api/v1/departments/{dept_id}', { params: { path: { dept_id: id } }, body }),
      ERRO,
    ),
}
