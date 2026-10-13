# 17. Identidade visual

Nome, cores, tipografia e logotipo do **TicketFlow**. Estas definições viram os *tokens* do design system na Fase 0 (`F0-06`, [ADR 0008](adr/0008-reka-ui.md)).

## 17.1 Nome

- **TicketFlow**, em uma palavra, com T e F maiúsculos. Sem tradução.
- Aparece na tela de login, no topo do menu lateral, no título da aba do navegador (`#1234 · Impressora do 3º andar · TicketFlow`) e no remetente dos e-mails ("TicketFlow – Martiniti").
- O nome fica em `settings.app_name` (padrão "TicketFlow"), para outra instalação poder trocar. Os identificadores técnicos não mudam: pacote `chamados`, serviço `ticketflow`, banco `chamados`.

## 17.2 Cores

As cores da Martiniti são **laranja, cinza e branco**. A interface é majoritariamente **branca e cinza**, e o **laranja marca a identidade e as ações principais**.

> **Personalização (2026-10-10):** o administrador troca as três cores em **Administração › Configurações** ([13](13-telas-e-navegacao.md#133-lista-de-telas)): cor da **marca** (laranja), cor **neutra** (cinza) e cor de **fundo** do modo claro (branco). Com as cores padrão (`#F97316`, `#737373`, `#FFFFFF`) vale a paleta abaixo, escolhida à mão. Com outras cores, a interface deriva a paleta inteira delas (`frontend/src/tema/paleta.ts`), no espaço de cor OKLCH: mantém o matiz e escurece ou clareia o tom até cumprir os contrastes da seção 17.3, nos dois modos. Assim o laranja oficial da Martiniti, quando chegar, é só digitado na tela. A tela também oferece **combinações prontas** (padrão laranja, azul, verde, azul-petróleo, roxo, âmbar e grafite, em `PREDEFINIDAS`), testadas quanto ao contraste; vermelho e rosa ficam de fora porque se confundiriam com o botão destrutivo e a prioridade alta. O modo escuro usa a cor neutra como base dos fundos; a cor de fundo escolhida vale só no modo claro. As cores de status, prioridade e do botão destrutivo não mudam.

### Paleta base

| Token | Claro | Escuro | Uso |
|-------|-------|--------|-----|
| `brand-500` | `#F97316` | `#F97316` | Laranja da marca: logotipo, faixa no topo dos e-mails, detalhes decorativos. **Nunca** como fundo de texto branco |
| `primary` | `#C2410C` (orange-700) | `#FB923C` (orange-400) | Botão principal, links, aba e item de menu ativos |
| `primary-hover` | `#9A3412` (orange-800) | `#FDBA74` (orange-300) | Hover do botão principal |
| `on-primary` | `#FFFFFF` | `#0A0A0A` | Texto sobre `primary` |
| `primary-subtle` | `#FFF7ED` (orange-50) | `#262626` (neutral-800) | Fundo do item de menu ativo e de destaques |
| `focus-ring` | `#EA580C` (orange-600) | `#FB923C` (orange-400) | Contorno de foco do teclado (2 px + 2 px de afastamento) |
| `bg` | `#FAFAFA` (neutral-50) | `#0A0A0A` (neutral-950) | Fundo da página |
| `surface` | `#FFFFFF` | `#171717` (neutral-900) | Cartões, tabelas, modais |
| `surface-raised` | `#F5F5F5` (neutral-100) | `#262626` (neutral-800) | Cabeçalho de tabela, menus suspensos |
| `text` | `#171717` (neutral-900) | `#F5F5F5` (neutral-100) | Texto principal |
| `text-muted` | `#525252` (neutral-600) | `#A3A3A3` (neutral-400) | Texto secundário, datas, rótulos |
| `border` | `#E5E5E5` (neutral-200) | `#262626` (neutral-800) | Divisórias decorativas |
| `border-input` | `#737373` (neutral-500) | `#737373` (neutral-500) | Borda de campos de formulário |

O **botão principal** é laranja escuro com texto branco; o **secundário** é branco com borda cinza; o **destrutivo** (cancelar chamado, reprovar) é vermelho (`#B91C1C` no claro, `#DC2626` no escuro).

### Cores de status e prioridade

O laranja fica **reservado para a marca e as ações**: nenhum status ou prioridade usa laranja, para não confundir. A cor nunca é a única pista: todo badge tem texto, e a prioridade também tem um ícone.

| Badge | Claro (texto / fundo) | Escuro (texto / fundo) |
|-------|-----------------------|------------------------|
| Pendente | `#1D4ED8` / `#EFF6FF` (azul) | `#93C5FD` / `#262626` |
| Aguardando | `#6D28D9` / `#F5F3FF` (violeta) | `#C4B5FD` / `#262626` |
| Aguardando aprovação | `#0F766E` / `#F0FDFA` (verde-azulado) | `#5EEAD4` / `#262626` |
| Concluído | `#15803D` / `#F0FDF4` (verde) | `#86EFAC` / `#262626` |
| Cancelado | `#404040` / `#F5F5F5` (cinza) | `#D4D4D4` / `#262626` |
| Prioridade baixa | `#404040` / `#F5F5F5` · ícone ▽ | `#D4D4D4` / `#262626` |
| Prioridade média | `#1D4ED8` / `#EFF6FF` · ícone ◇ | `#93C5FD` / `#262626` |
| Prioridade alta | `#B91C1C` / `#FEF2F2` · ícone △ | `#FCA5A5` / `#262626` |
| Prioridade crítica | `#FFFFFF` / `#B91C1C` · ícone ▲ | `#FFFFFF` / `#DC2626` |

Status criados pelo administrador herdam a cor do `kind` deles.

## 17.3 Contraste (WCAG 2.1 AA)

Mínimos: **4,5:1** para texto e **3:1** para bordas de campos e contorno de foco ([RNF-11](02-requisitos.md#requisitos-não-funcionais)).

| Combinação | Contraste | Resultado |
|------------|----------:|-----------|
| Branco sobre `brand-500` `#F97316` | 2,80 | ❌ Por isso o laranja da marca não é usado em botões |
| Branco sobre `orange-600` `#EA580C` | 3,56 | ❌ para texto; ✅ como contorno de foco |
| Branco sobre `primary` `#C2410C` | 5,18 | ✅ Botão principal (claro) |
| `primary` `#C2410C` como texto de link sobre branco | 5,18 | ✅ |
| Escuro `#0A0A0A` sobre `primary` `#FB923C` | 8,75 | ✅ Botão principal (escuro) |
| `text` sobre `surface` | 17,93 / 16,44 | ✅ claro / escuro |
| `text-muted` sobre `surface` | 7,81 / 7,11 | ✅ claro / escuro |
| `border-input` sobre `surface` | 4,74 / 3,78 | ✅ claro / escuro |
| Badges de status e prioridade (claro) | 4,79 a 9,51 | ✅ |
| Badges de status e prioridade (escuro) | 4,83 a 10,78 | ✅ |

Os contrastes são conferidos de novo no CI do frontend sempre que um token de cor mudar (teste com `axe` no Playwright).

## 17.4 Modo claro e escuro

- Três opções no menu do usuário: **Claro**, **Escuro** e **Automático** (padrão, segue o sistema operacional). A escolha fica salva no perfil.
- Os tokens da seção 17.2 são variáveis CSS no `@theme` do Tailwind, redefinidas para o modo escuro. Os componentes usam **só os tokens** (`bg-surface`, `text-muted`), nunca cores diretas como `bg-orange-700`.
- Os testes do frontend conferem os contrastes da paleta padrão e de combinações difíceis de cores personalizadas (`tema/paleta.test.ts`).

## 17.5 Tipografia

| Uso | Fonte | Tamanho / peso |
|-----|-------|----------------|
| Interface | **Inter**, instalada junto com o frontend (`@fontsource-variable/inter`), sem carregar de servidores externos. Alternativa: `system-ui` | 14 px no corpo; 13 px em tabelas densas |
| Títulos de página | Inter | 20 px, peso 600 |
| Título do chamado | Inter | 18 px, peso 600 |
| Número do chamado e códigos | **JetBrains Mono** (ou `ui-monospace`) | Mesmo tamanho do texto ao redor |

Números em tabelas usam algarismos de largura fixa (`font-variant-numeric: tabular-nums`) para alinhar as colunas.

## 17.6 Logotipo

O administrador pode enviar o logotipo da empresa em **Configurações** (PNG, JPEG ou WebP, até 256 KB; SVG não é aceito porque pode conter scripts). Ele aparece no topo do menu e na tela de login, no lugar do provisório descrito abaixo.

- **Até existir um logotipo próprio**, o TicketFlow usa um logotipo de texto: um quadrado arredondado em `brand-500` com um "T" branco em negrito, seguido de "TicketFlow" em Inter peso 700. O quadrado sozinho serve de ícone da aba (favicon) e de ícone do aplicativo no celular.
- O **logotipo da Martiniti** entra pelas Configurações e aparece na tela de login, abaixo do nome TicketFlow, e no rodapé dos e-mails.
- Um logotipo próprio do TicketFlow pode ser encomendado depois sem mudar nada no código: ele fica num único componente (`AppLogo.vue`) e nos arquivos de ícone.

## 17.7 E-mails

- Largura máxima de 600 px, fundo branco e uma **faixa laranja `brand-500` de 4 px no topo**, decorativa e sem texto.
- Botão de ação com as cores do botão principal (`#C2410C`, texto branco).
- Rodapé em `text-muted`, com o logotipo da Martiniti e o link para as preferências de notificação.
- Sempre com uma versão em texto puro.

## 17.8 Tom de voz

- Português simples e direto, tratando o usuário por "você".
- Botões com verbos: "Registrar", "Assumir", "Concluir", e não "OK" ou "Enviar" sem contexto.
- Mensagens de erro dizem o que aconteceu e o que fazer ("Este chamado foi alterado pela Ana. Recarregue para ver a versão atual.").
