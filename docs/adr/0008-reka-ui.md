# 0008. Componentes de interface com Reka UI + Tailwind CSS

- **Status:** Substituída por [0011](0011-interface-web-no-servidor.md)
- **Data:** 2026-10-09

## Contexto

A interface em Vue ([ADR 0007](0007-interface-web-vue.md)) precisa de componentes complexos (select com busca, combobox, diálogos, menus, abas, popovers, date picker) que sejam **acessíveis** (WCAG 2.1 AA, requisito RNF-11) e estilizados com Tailwind.

## Decisão

- Usar **Reka UI** (*headless*: comportamento, foco, teclado e ARIA prontos, sem estilo) como base dos componentes interativos.
- Construir o **design system próprio** em `frontend/src/components/ui/`, estilizado com Tailwind (cores, espaçamento e tipografia como tokens de tema), envolvendo os primitivos do Reka UI.
- As telas usam **só** os componentes de `components/ui/`, nunca o Reka UI diretamente, para manter o visual consistente e facilitar uma troca futura.
- Ícones: um único pacote de ícones SVG (ex.: Lucide), importados sob demanda.

## Alternativas consideradas

- **PrimeVue em modo *unstyled*:** mais componentes prontos (tabela de dados, editor), mas a integração com Tailwind é mais trabalhosa e o visual tende a ficar "genérico".
- **Componentes 100% próprios:** controle total, mas acessibilidade (foco, leitores de tela, teclado) é difícil de acertar e consome muito tempo.

## Consequências

- Mais trabalho inicial no design system (Fase 0) em troca de acessibilidade e consistência.
- Componentes que o Reka UI não oferece (tabela de dados com ordenação e paginação, editor de texto rico) precisam ser escolhidos à parte. Sugestão: TanStack Table (headless) e Tiptap (editor Markdown/rich text).
