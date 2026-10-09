# 0007. Interface web: SPA em Vue 3 + TypeScript + Tailwind CSS

- **Status:** Aceita
- **Data:** 2026-10-09
- **Substitui:** [0006](0006-interface-web.md)

## Contexto

O [ADR 0006](0006-interface-web.md) escolheu renderização no servidor (Jinja2 + HTMX) para manter a equipe só em Python. A decisão foi revista: o time prefere **Vue**, por oferecer uma experiência mais rica para os agentes (filas que se atualizam, edição inline, atalhos de teclado) e uma separação clara entre o backend (API) e a interface.

## Decisão

- **SPA em Vue 3** (Composition API com `<script setup>`) e **TypeScript**.
- **Vite** para desenvolvimento e build; **pnpm** como gerenciador de pacotes.
- **Tailwind CSS** para estilo, com um conjunto de componentes base acessíveis (biblioteca em [questões em aberto](../questoes-em-aberto.md)).
- **Vue Router** com guardas por papel; **Pinia** para estado da sessão e preferências; **TanStack Query (Vue)** para cache, revalidação e paginação dos dados da API.
- **Cliente da API gerado do OpenAPI** (`openapi-typescript` + `openapi-fetch`): o backend é a fonte de verdade dos tipos, e o CI falha se o cliente gerado estiver desatualizado.
- **vue-i18n** com textos em pt-BR desde o início.
- **Autenticação por cookie de sessão** `HttpOnly` na mesma origem, com token CSRF em header. Nenhum token de acesso no `localStorage`.
- **Entrega:** o build do frontend é feito em uma etapa do Dockerfile e servido como arquivos estáticos pelo container da API, na mesma origem. A instalação continua sendo *app + PostgreSQL*.
- **Qualidade:** ESLint + Prettier, `vue-tsc`, Vitest + Vue Test Utils, Playwright nos fluxos principais.

## Alternativas consideradas

- **Jinja2 + HTMX + Tailwind (ADR 0006):** uma só linguagem e nenhum build de Node, mas com interatividade mais limitada e a interface acoplada ao backend.
- **React:** ecossistema maior, mas o time prefere Vue, que tem curva de aprendizado menor e cobre bem as necessidades do projeto.
- **Nuxt (SSR):** desnecessário: a interface fica atrás de login, SEO não importa e o SSR exigiria um servidor Node em produção.

## Consequências

- A equipe passa a manter duas stacks (Python e TypeScript). O Node.js é necessário em desenvolvimento e no build, mas **não** em produção.
- O princípio *API-first* fica mais forte: toda tela usa apenas a API pública, a mesma usada por integrações e agentes de IA.
- Mudanças na API exigem regenerar o cliente TypeScript. Mudanças incompatíveis aparecem como erro de tipo no build.
- Atualização em tempo real: no início, revalidação periódica via TanStack Query. Se for necessário, um endpoint de Server-Sent Events (SSE) para filas e chamados abertos.
- Acessibilidade (WCAG 2.1 AA) passa a ser responsabilidade dos componentes Vue: foco, navegação por teclado e ARIA precisam ser testados.
