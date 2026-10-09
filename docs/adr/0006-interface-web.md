# 0006. Interface web com Jinja2 + HTMX + Tailwind CSS

- **Status:** Aceita
- **Data:** 2026-10-09

## Contexto

A interface precisa atender solicitantes e agentes, ser responsiva e acessível (WCAG 2.1 AA) e ser mantida por uma equipe que trabalha em Python.

## Decisão

- **Tailwind CSS** para estilo.
- **Renderização no servidor** com templates **Jinja2** servidos pelo próprio FastAPI (módulo `web/`).
- **HTMX** para interatividade sem SPA: atualização parcial de listas, formulários inline, filtros e paginação.
- O Tailwind é compilado pelo **executável standalone** (sem Node.js e sem `npm`), tanto em desenvolvimento (`--watch`) quanto em uma etapa do build da imagem Docker. O CSS final é servido como arquivo estático.
- As rotas web chamam os mesmos *services* da API REST, então nenhuma regra de negócio fica só na interface.

## Alternativas consideradas

- **SPA (React/Vue) + Tailwind consumindo a API:** experiência mais rica, mas exige uma segunda stack (Node, build, estado no cliente) e duplica validações.
- **Componentes prontos (Bootstrap):** menos controle visual que o Tailwind.

## Consequências

- Uma única linguagem e um único deploy.
- Telas muito interativas (ex.: editor de fluxos de automação) podem exigir JavaScript pontual. Avaliar Alpine.js (ver [questões em aberto](../questoes-em-aberto.md)).
- As classes do Tailwind são lidas dos templates: a configuração de `content`/`@source` precisa apontar para `src/chamados/web/templates`.
