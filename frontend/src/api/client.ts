import createClient, { type Middleware } from 'openapi-fetch'

import { idiomaAtual } from '@/i18n'

import type { components, paths } from './schema'

export type Schemas = components['schemas']

function cookie(nome: string): string | undefined {
  return document.cookie
    .split('; ')
    .find((c) => c.startsWith(`${nome}=`))
    ?.slice(nome.length + 1)
}

export const SESSAO_EXPIRADA = 'tf:sessao-expirada'

const sessao: Middleware = {
  onRequest({ request }) {
    // As mensagens de erro da API vêm no idioma escolhido na interface (core/i18n.py).
    request.headers.set('Accept-Language', idiomaAtual())
    // CSRF por token sincronizado: o cookie tf_csrf volta no header (docs/09 §9.7).
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) {
      const csrf = cookie('tf_csrf')
      if (csrf) request.headers.set('X-CSRF-Token', csrf)
    }
    return request
  },
  onResponse({ request, response }) {
    // Sessão expirada no meio do uso: o App manda para o login e volta depois.
    if (response.status === 401 && !new URL(request.url).pathname.startsWith('/api/v1/auth/')) {
      window.dispatchEvent(new Event(SESSAO_EXPIRADA))
    }
    return response
  },
}

// Mesma origem da página: a API e a SPA são servidas juntas (ADR 0010).
// O fetch é resolvido a cada chamada (e não na criação do cliente) para os testes poderem simulá-lo.
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  fetch: (request) => globalThis.fetch(request),
})
api.use(sessao)

/** Texto do erro para mostrar ao usuário: o `detail` da API (RFC 9457) ou uma mensagem padrão. */
export function mensagemDeErro(erro: unknown, padrao: string): string {
  if (erro && typeof erro === 'object' && 'detail' in erro && typeof erro.detail === 'string') {
    return erro.detail
  }
  return padrao
}

/** Lança o erro da API (com a mensagem pronta) ou devolve os dados. */
export function ou<T>(resultado: { data?: T; error?: unknown }, padrao: string): T {
  if (resultado.error !== undefined || resultado.data === undefined) {
    throw new Error(mensagemDeErro(resultado.error, padrao))
  }
  return resultado.data
}
