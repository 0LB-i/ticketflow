# 10. Como funcionam os chamados

Este documento descreve o ciclo de vida de um chamado, do ponto de vista de quem pede e de quem atende. As permissões citadas estão em [Organização e permissões](08-organizacao-e-permissoes.md).

## 10.1 Anatomia de um chamado

| Campo | Descrição | Quem define |
|-------|-----------|-------------|
| Número | `#1234`, sequencial, nunca reutilizado | Sistema |
| Título e descrição | O que está acontecendo ou sendo pedido (Markdown) | Solicitante |
| Tipo | Incidente, requisição ou dúvida (10.2) | Padrão da categoria; agente ajusta |
| Categoria | Item do catálogo de serviços | Solicitante; agente ajusta |
| Campos extras | Definidos pela categoria (ex.: patrimônio, sistema, centro de custo) | Solicitante |
| Solicitante | Quem precisa do atendimento | Sistema (usuário logado) ou agente, ao abrir em nome de alguém |
| Aberto por | Quem registrou, se diferente do solicitante | Sistema |
| Setor | Setor do solicitante **no momento da abertura** | Sistema |
| Grupo | Fila responsável | Categoria (roteamento); agente transfere |
| Responsável | Agente que está atendendo | Agente assume ou supervisor atribui |
| Status | Etapa do ciclo de vida (10.5) | Fluxo |
| Impacto, urgência e prioridade | 10.3 | Solicitante informa a urgência; agente define o impacto |
| Canal | Portal, e-mail, telefone, presencial, API ou agente de IA | Sistema |
| Observadores | Pessoas que acompanham | Solicitante e agentes |
| Tags | Marcadores livres | Agentes |
| Vínculos | Duplicado de, relacionado a, bloqueado por | Agentes |
| Anexos | Ver [Anexos e arquivos](11-anexos-e-arquivos.md) | Todos que comentam |
| Resolução | Código + texto da solução | Agente |
| Avaliação | Nota de 1 a 5 + comentário | Solicitante |

## 10.2 Tipos de chamado

| Tipo | Quando usar | Exemplo | Efeito |
|------|-------------|---------|--------|
| **Incidente** | Algo que funcionava parou ou está com defeito | "Não consigo acessar o ERP" | Foco em restaurar o serviço |
| **Requisição** | Pedido de algo novo ou de uma mudança padrão | "Acesso à pasta do Financeiro", "Notebook para novo colaborador" | Pode exigir **aprovação** (10.8) |
| **Dúvida** | Orientação, sem nada quebrado | "Como configuro a assinatura de e-mail?" | Boa candidata a artigo da base de conhecimento |

O tipo vem da categoria e o agente pode corrigi-lo. Ele é usado nos relatórios.

## 10.3 Prioridade: impacto × urgência

O solicitante não escolhe "prioridade" diretamente, porque todo mundo escolheria "alta". Ele responde duas perguntas simples:

- **Urgência:** "Isso impede seu trabalho?" → *Posso esperar* / *Atrapalha, mas consigo trabalhar* / *Estou parado*
- **Impacto:** "Quem é afetado?" → *Só eu* / *Meu setor ou equipe* / *A empresa toda ou clientes*

| Impacto \ Urgência | Baixa | Média | Alta |
|--------------------|-------|-------|------|
| **Individual** | Baixa | Baixa | Média |
| **Setor / equipe** | Baixa | Média | Alta |
| **Empresa / clientes** | Média | Alta | **Crítica** |

- O agente pode corrigir o impacto e a urgência; a prioridade é recalculada.
- O agente pode **forçar** outra prioridade, mas precisa informar o motivo, que fica no histórico.
- A matriz é configurável pelo administrador.

## 10.4 Abertura

### Canais

| Canal | Como funciona | Fase |
|-------|---------------|------|
| **Portal** | Formulário guiado (abaixo) | 1 |
| **Em nome de alguém** | O agente registra um atendimento por telefone ou presencial, escolhendo o solicitante. O canal fica como `phone` ou `walk_in` | 1 |
| **E-mail** | Mensagem para o endereço de um grupo (ex.: `ti@empresa.com`) vira chamado na categoria padrão desse grupo. Remetente que não é usuário recebe uma resposta automática explicando como acessar o portal | 2 |
| **API / integrações** | `POST /tickets` com token de API | 2 |
| **Agente de IA / MCP** | Via API ou servidor MCP, identificado como `ai_agent` | 4 |

### Formulário guiado do portal

```
1. "Do que você precisa?"  → busca + árvore do catálogo (categorias com ícone e descrição)
2. Artigos sugeridos        → "Isso resolve?" (deflexão; reforçada por IA na Fase 4)
3. Formulário               → título, descrição, campos extras da categoria, urgência, impacto, anexos
4. Confirmação              → número do chamado e link para acompanhar
```

Ao enviar o formulário:

1. O sistema calcula a prioridade, define o grupo pela categoria e grava o setor do solicitante.
2. Se a categoria **exige aprovação**, o chamado nasce no status de aprovação (10.8).
3. Senão, nasce em **Pendente**, na fila do grupo e sem responsável.
4. O solicitante recebe a confirmação por e-mail.
5. O grupo é notificado conforme a configuração do grupo: e-mail para todos os membros ou só a fila.

## 10.5 Status e fluxo

> As etapas abaixo são o **padrão proposto** e ainda serão discutidas pela equipe. O administrador pode criar outras.

### Status padrão

| Status | `kind` | Significado |
|--------|--------|-------------|
| **Pendente** | `open` | Chamado em aberto: na fila do grupo (sem responsável) ou em atendimento |
| **Aguardando cliente** | `waiting` | O agente pediu uma informação ou ação ao solicitante. "Cliente" é quem abriu o chamado, sempre um colaborador interno |
| **Entregue** | `resolved` | O agente entregou a solução; falta concluir |
| **Concluído** | `closed` | Final |
| **Cancelado** | `canceled` | Final. Não era necessário, era duplicado ou foi reprovado |

**Status criados pelo administrador:** cada um tem um nome e um `kind`: `open`, `waiting`, `resolved`, `closed`, `canceled` ou `approval` (usado nas aprovações, 10.8). As regras do sistema dependem do `kind`, não do nome. Exemplos: "Em análise" (`open`), "Aguardando aprovação" (`approval`). Entre status do mesmo `kind`, o agente muda livremente.

**Nada muda de status sozinho com o passar do tempo:** não há fechamento automático. Concluir é sempre uma ação de uma pessoa.

### Diagrama

```mermaid
stateDiagram-v2
    [*] --> Pendente
    [*] --> AguardandoAprovacao: categoria exige aprovação
    AguardandoAprovacao --> Pendente: aprovado
    AguardandoAprovacao --> Cancelado: reprovado
    Pendente --> AguardandoCliente: agente pergunta
    AguardandoCliente --> Pendente: solicitante responde
    Pendente --> Entregue: solução informada
    Entregue --> Concluido: concluído manualmente
    Entregue --> Pendente: reaberto
    Pendente --> Cancelado
    AguardandoCliente --> Cancelado
    Concluido --> [*]
    Cancelado --> [*]
```

### Transições: quem pode e o que é exigido

| De | Para | Quem | Exigências / efeitos |
|----|------|------|----------------------|
| Aprovação (`approval`) | Pendente | Aprovador | Comentário opcional |
| Aprovação (`approval`) | Cancelado | Aprovador | **Motivo obrigatório**, enviado ao solicitante |
| Pendente | Aguardando cliente | Responsável | **Comentário público obrigatório** (a pergunta) |
| Aguardando cliente | Pendente | Solicitante ou agente | Volta quando o solicitante responde, ou manualmente pelo agente |
| Pendente | Entregue | Responsável | **Solução (texto público) + código de resolução obrigatórios** |
| Entregue | Concluído | Agente do grupo ou solicitante (**a definir**) | Sempre manual |
| Entregue | Pendente | Solicitante ou agente | **Motivo obrigatório**. Contador de reaberturas +1. Volta para o mesmo responsável |
| Pendente, Aguardando cliente, aprovação | Cancelado | Solicitante | Só os próprios chamados. Motivo opcional |
| Qualquer não final | Cancelado | Agente | **Motivo obrigatório** (ex.: duplicado → usar mesclagem) |
| Concluído | — | — | Final. O botão "Abrir novo chamado relacionado" cria um chamado vinculado |

### Códigos de resolução

Resolvido · Resolvido com solução de contorno · Não reproduzível · Fora do escopo do grupo. A lista é configurável e serve para os relatórios.

## 10.6 Como o agente trabalha

### Visões (filas) padrão

| Visão | Conteúdo | Para quem |
|-------|----------|-----------|
| **Não atribuídos** | Chamados dos meus grupos sem responsável | Agentes |
| **Meus chamados** | Chamados em que sou o responsável, ainda abertos | Agentes |
| **Aguardando minha ação** | Meus chamados com resposta nova do solicitante, recém-aprovados ou reabertos | Agentes |
| **Aguardando cliente** | Chamados dos meus grupos esperando o solicitante | Agentes |
| **Entregues** | Chamados entregues que ainda não foram concluídos | Agentes |
| **Todos do grupo** | Tudo do grupo, com filtro por responsável | Supervisores |
| **Visões salvas** | Filtros personalizados, pessoais ou do grupo | Todos (Fase 2) |

**Ordenação padrão:** primeiro a prioridade, depois a data de abertura (mais antigo primeiro).

**Indicadores na lista:** prioridade (cor), ícone de "resposta nova", responsável, há quanto tempo está parado.

### Distribuição do trabalho

- **Puxar (padrão):** o agente clica em **"Pegar o próximo"**, e o sistema atribui o primeiro chamado da fila "Não atribuídos" na ordenação padrão. Isso evita escolher só os chamados fáceis. O agente também pode assumir um chamado específico.
- **Empurrar:** o supervisor atribui chamados a membros do grupo, individualmente ou em massa.
- **Automática** (futuro): por rodízio ou menor carga.

### Tela do chamado (agente)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ #1234  Impressora do 3º andar não imprime     [Pendente ▾] [Alta]            │
│ Aberto há 2h10  ·  Maria também está vendo                                   │
├───────────────────────────────────────────────┬──────────────────────────────┤
│ LINHA DO TEMPO                                │ SOLICITANTE                  │
│ ● João (solicitante) · 09:02                  │ João Silva · Financeiro      │
│   Desde hoje cedo aparece "offline"…          │ ramal 4321 · 3 chamados/90d  │
│ ◦ Sistema · atribuído a Ana · 09:15           │──────────────────────────────│
│ ▒ Ana · NOTA INTERNA · 09:20                  │ Grupo: TI – Service Desk     │
│ ▒  Verificar switch do andar                  │ Responsável: Ana             │
│ ● Ana · 09:25                                 │ Categoria: TI › Impressão    │
│   Pode reiniciar a impressora?                │ Tipo: Incidente              │
│                                               │ Tags · Campos extras         │
│                                               │ Observadores · Vínculos      │
│                                               │ Anexos (2)                   │
├───────────────────────────────────────────────┤──────────────────────────────│
│ [Responder ao solicitante] [Nota interna]     │ Sugestões da IA (Fase 3)     │
│ ┌───────────────────────────────────────────┐ │ · Resumo                     │
│ │                                           │ │ · Resposta sugerida          │
│ └───────────────────────────────────────────┘ │ · Chamados semelhantes       │
│ 📎 Anexar  ⚡ Resposta pronta                  │                              │
│ [Enviar]  [Enviar e aguardar cliente ▾]       │                              │
└───────────────────────────────────────────────┴──────────────────────────────┘
```

- **Público × interno:** notas internas têm fundo e rótulo diferentes e uma confirmação visual antes de enviar. Trocar de aba não apaga o rascunho.
- **Enviar e mudar status:** a resposta e a mudança de status saem numa única ação (ex.: "Enviar e entregar", "Enviar e aguardar cliente").
- **Menções:** `@nome` em nota interna notifica o colega, que ganha acesso de leitura ao chamado se ainda não tiver.
- **Colisão:** o sistema mostra quem mais está com o chamado aberto. Se chegou um comentário novo depois que a tela foi carregada, aparece um aviso antes de enviar. Alterações de campos usam `ETag` para não sobrescrever a mudança de outra pessoa.
- **Rascunho automático:** o texto em edição é salvo localmente no navegador e restaurado se a página for recarregada.
- **Histórico do solicitante:** acesso rápido aos últimos chamados da mesma pessoa.
- **Atalhos de teclado** (Fase 2): `j`/`k` navegar, `a` assumir, `r` responder, `n` nota interna.

### Respostas prontas (macros)

- Texto com variáveis (`{{solicitante.nome}}`, `{{chamado.numero}}`, `{{agente.nome}}`).
- Podem incluir **ações**: mudar status, adicionar tag, mudar categoria.
- Escopo: **pessoal**, **do grupo** (gerenciada pelo supervisor) ou **global** (admin).

### Transferência e escalonamento

| Situação | Como funciona |
|----------|---------------|
| **Transferência** (escalonamento funcional, ex.: N1 → N2) | O agente escolhe o grupo de destino e escreve um **motivo obrigatório** (nota interna). O chamado continua **Pendente**, na fila do novo grupo e sem responsável. O grupo anterior mantém acesso de leitura. Na Fase 3 a IA pode gerar um resumo para quem recebe |
| **Pedir ajuda sem transferir** | Nota interna com `@menção` a um colega de outro grupo |

### Duplicados e vínculos

- **Mesclar:** o chamado secundário é **cancelado** com o código "Duplicado" e vinculado ao principal (`duplicate_of`). O solicitante do secundário vira **observador** do principal e é avisado. Os conteúdos não são movidos: o vínculo permite consultar os dois.
- **Relacionado a / bloqueado por:** só informativos, exibidos nos dois chamados.

### Ações em massa (supervisor ou permissão `ticket.bulk`)

Atribuir, transferir, mudar prioridade, adicionar tag, entregar com a mesma solução (ex.: incidente geral resolvido) e adicionar comentário público.

## 10.7 Experiência do solicitante

- **Meus chamados:** lista com status em linguagem simples ("Estamos trabalhando nisso", "Precisamos de uma resposta sua").
- **Detalhe:** só a parte pública: comentários, anexos públicos, status e quem está atendendo.
- **Ações:** responder, anexar, adicionar observadores, concluir ("Resolveu"), reabrir ("Não resolveu", com motivo), cancelar e avaliar.
- **Por e-mail** (Fase 2): responder ao e-mail de notificação adiciona um comentário ao chamado.
- **Gestor de setor:** abas "Chamados do meu setor" (somente leitura) e "Aprovações pendentes".

### Regras de edição

- O solicitante edita título e descrição **até o atendimento começar**. Depois disso, só comenta.
- Comentários podem ser editados pelo autor por **10 minutos**. As versões anteriores ficam no histórico.
- **Ninguém apaga comentários.** Com `ticket.hide_content`, um comentário ou anexo pode ser **ocultado**, com motivo, e o original continua na auditoria (ex.: alguém colou uma senha).

## 10.8 Aprovações (Fase 2)

- Ativadas **por categoria** (`requires_approval`).
- **Quem aprova**, configurado na categoria:
  - **gestor do setor do solicitante** (padrão); se houver vários, qualquer um decide;
  - um **usuário específico** (ex.: diretor financeiro);
  - **qualquer membro de um grupo** (ex.: Segurança da Informação).
- Se o solicitante for o próprio gestor, a aprovação sobe para o gestor do setor acima. Se não houver, o chamado vai para o administrador.
- O aprovador recebe um e-mail com link e decide na tela: **Aprovar** (comentário opcional) ou **Reprovar** (motivo obrigatório).
- Para usar aprovações, o administrador cria um status com `kind = approval` (ex.: "Aguardando aprovação"). Ele não faz parte dos status padrão.
- Lembretes após 1 e 3 dias. O administrador pode redirecionar a aprovação a outra pessoa (ex.: aprovador de férias).
- Fase 2: um nível de aprovação. Aprovação em vários níveis e delegação por férias ficam para o futuro.

## 10.9 Prazos: sem SLA

Não há SLA: o atendimento é todo interno, e não existem metas de prazo, alertas de vencimento nem calendário de expediente (decisão de 2026-10-09). O sistema só **mede** os tempos (até a 1ª resposta, até a entrega, até a conclusão) para os relatórios.

## 10.10 Notificações

| Evento | Solicitante | Observadores | Responsável | Grupo | Supervisor | Outros |
|--------|:-:|:-:|:-:|:-:|:-:|---|
| Chamado aberto | ✉️ confirmação | | | ✉️/🔔 conforme o grupo | | |
| Aguardando aprovação | | | | | | Aprovador ✉️🔔 |
| Aprovado / reprovado | ✉️🔔 | | | 🔔 (aprovado) | | |
| Atribuído | | | ✉️🔔 | | | |
| Comentário público do agente | ✉️🔔 | ✉️ | | | | |
| Resposta do solicitante | | | ✉️🔔 | 🔔 se sem responsável | | |
| Nota interna com @menção | | | | | | Mencionado 🔔 |
| Transferido | | | | 🔔 novo grupo | | |
| Entregue | ✉️ com "Concluir" / "Não resolveu" | ✉️ | | | | |
| Reaberto | | | ✉️🔔 | | | |
| Concluído | ✉️ pesquisa de satisfação | | | | | |
| Avaliação ≤ 2 | | | 🔔 | | 🔔 | |

✉️ e-mail · 🔔 notificação dentro do sistema (Fase 2). Cada usuário escolhe nas preferências como quer receber, exceto as notificações essenciais (aprovação pendente, pedido de resposta, entregue), que não podem ser desligadas.

## 10.11 Rotinas automáticas (worker)

| Rotina | Frequência |
|--------|------------|
| Lembrar aprovadores | Diária |
| Limpar uploads não vinculados há mais de 24 h | Diária |
| Ler a caixa de e-mail de entrada | A cada minuto (Fase 2) |

Nenhuma rotina muda o status de um chamado.

## 10.12 Avaliação de satisfação (Fase 2)

Após a **conclusão**, o solicitante recebe um único convite: nota de 1 a 5 e comentário opcional, respondidos com um clique no e-mail ou no portal. Uma nota ≤ 2 avisa o responsável e o supervisor. Ninguém é obrigado a responder.
