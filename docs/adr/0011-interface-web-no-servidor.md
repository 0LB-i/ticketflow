# 0011. Interface web renderizada no servidor: Jinja2 + HTMX + Tailwind CSS

- **Status:** Aceita (migração concluída em 2026-10-19)
- **Data:** 2026-10-17
- **Substitui:** [0007](0007-interface-web-vue.md) e [0008](0008-reka-ui.md)
- **Andamento:** [docs/19](../19-migracao-da-interface.md)

## Contexto

Com a SPA em Vue ([ADR 0007](0007-interface-web-vue.md)), o projeto tem duas stacks. Toda mudança na API exige regenerar o cliente TypeScript, e cada mudança passa por mais um conjunto de ferramentas (vue-tsc, ESLint, Prettier, Vitest e o build do Vite), além de outra linguagem. O desenvolvimento ficou mais lento e mais pesado do que o ganho de interatividade justifica.

O NetKeep, outro sistema da mesma equipe, usa Jinja2 + HTMX + Tailwind sobre FastAPI e PostgreSQL, com uma linguagem só e sem Node. O backend do TicketFlow já está nessa stack: muda só a interface.

## Decisão

- **Telas em Jinja2**, renderizadas pelo próprio FastAPI, no pacote `backend/src/chamados/web/` (templates, arquivos estáticos e as rotas das telas). O **HTMX** troca trechos da página quando for preciso, e o JavaScript que sobrar é puro, em `web/static/js/`, sem build.
- **Tailwind CSS 4** pelo binário standalone (`pytailwindcss`, `scripts/css.sh`), sem Node. O `app.css` não vai para o git: o deploy o gera, e na máquina de desenvolvimento um serviço o gera de novo a cada mudança nos templates. Os tokens de cor e o modo escuro são os mesmos da SPA.
- **As telas não têm regra de negócio.** Uma rota de tela chama a mesma função da rota da API, ou o mesmo service, e só monta o HTML. As permissões continuam no backend (`allowed_actions`, `can`, filtro de visibilidade).
- **A API JSON (`/api/v1`) continua**, para integrações e agentes de IA.
- **Mesma sessão e mesmo CSRF:** o cookie `tf_sessao`. Os formulários que alteram dados mandam o token CSRF num campo escondido (`csrf_token`), e o HTMX o manda no header.
- **Editor:** o Tiptap continua, num arquivo único já empacotado em `web/static/js/vendor/`. O Node volta a ser necessário só para atualizar esse arquivo.
- **Idiomas:** os mesmos catálogos JSON da SPA, com `t()` nos templates; na troca final, eles passaram para `web/locales/`.
- **Migração tela a tela.** Enquanto a SPA existir, o Vite repassa ao uvicorn os endereços das telas já migradas, e a SPA recarrega a página quando navega para uma delas (`ServerView.vue`). Na troca final saem o `frontend/`, o Node do deploy e o serviço do Vite, e o nginx de desenvolvimento passa a mandar tudo para o uvicorn.

## Alternativas consideradas

- **Manter a SPA em Vue:** mantém a interatividade rica, mas também as duas stacks e o custo de cada mudança, que é justamente o problema.
- **Jinja2 sem HTMX:** ainda mais simples, mas cada ação recarregaria a página inteira (filas, comentários, mudanças de status).
- **Reescrever tudo de uma vez:** sem código provisório, mas nada poderia ser conferido no navegador até o fim.

## Consequências

- Uma linguagem e um conjunto de ferramentas só (ruff, mypy, pytest). Nada a regenerar quando a API muda.
- Sem tipos entre a API e a tela: os testes das telas (pytest, conferindo o HTML) passam a cobrir esse contrato.
- A interatividade fica limitada ao que o HTMX e um pouco de JavaScript resolvem. Atualização em tempo real, se for preciso, por SSE com HTMX.
- Durante a migração, as duas interfaces convivem, com algum código provisório na SPA e no `vite.config.ts`.
- Acessibilidade (WCAG 2.1 AA) passa a ser dos templates: HTML semântico, foco e ARIA nos macros de `templates/_ui.html`.
