import createClient from 'openapi-fetch'

import type { paths } from './schema'

/** Cliente tipado gerado do OpenAPI do backend (`pnpm gen:api`, docs/03). */
// Mesma origem da página: a API e a SPA são servidas juntas (ADR 0010).
// O fetch é resolvido a cada chamada (e não na criação do cliente) para os testes poderem simulá-lo.
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  fetch: (request) => globalThis.fetch(request),
})
