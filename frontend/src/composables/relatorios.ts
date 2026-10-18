import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'

import { api, mensagemDeErro, ou, type Schemas } from '@/api/client'

export type Relatorio = Schemas['Report']
/** Período (datas "AAAA-MM-DD", o fim incluído) e filtros; vazio = todos. */
export interface FiltroRelatorio {
  start: string
  end: string
  team?: string
  person?: string
  client?: string
}

/** Grupos e pessoas que a pessoa logada pode escolher nos filtros. */
export function useOpcoesRelatorio() {
  return useQuery({
    queryKey: ['relatorios', 'opcoes'],
    queryFn: async () => ou(await api.GET('/api/v1/reports/options')),
  })
}

export function useRelatorio(filtro: MaybeRefOrGetter<FiltroRelatorio>) {
  return useQuery({
    queryKey: computed(() => ['relatorios', toValue(filtro)]),
    queryFn: async () =>
      ou(await api.GET('/api/v1/reports', { params: { query: toValue(filtro) } })),
    // Ao trocar o filtro, os gráficos continuam na tela até os números novos chegarem.
    placeholderData: keepPreviousData,
  })
}

/** Baixa o PDF com os mesmos filtros (pela API, para ir no idioma escolhido na interface). */
export async function baixarPdf(filtro: FiltroRelatorio) {
  const r = await api.GET('/api/v1/reports/pdf', {
    params: { query: filtro },
    parseAs: 'blob',
  })
  if (r.error !== undefined || !(r.data instanceof Blob)) throw new Error(mensagemDeErro(r.error))
  const url = URL.createObjectURL(r.data)
  const link = document.createElement('a')
  link.href = url
  link.download = `relatorio-${filtro.start}-a-${filtro.end}.pdf`
  link.click()
  URL.revokeObjectURL(url)
}
