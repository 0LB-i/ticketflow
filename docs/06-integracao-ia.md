# 6. Integração com IA

> **Fora da v1.0.** Na revisão de escopo de 2026-10-09, toda a integração com IA foi para o [backlog](07-roadmap.md#backlog-futuro-fora-da-v10). Este documento guarda o plano para quando ela entrar.
>
> **Em 2026-10-23 entrou a direção "a IA usa o sistema":** tokens de API, `Idempotency-Key` e o servidor MCP em `/mcp` (seções abaixo, marcadas **feito**). A direção "o sistema usa IA" (classificação, resumo, sugestão) continua no plano. Na coluna "Bloco", 1 vem antes de 2.
>
> **Atenção:** este plano foi escrito antes da mudança de modelo de 2026-10-10 ([08](08-organizacao-e-permissoes.md)) e ainda supõe um solicitante com conta (deflexão no portal, sugestão de resposta ao solicitante). Revisar quando a IA entrar no roadmap.

A integração acontece em **duas direções**:

1. **O sistema usa IA** (saída): chama modelos de linguagem e de embeddings para classificar, resumir, sugerir respostas e encontrar chamados semelhantes.
2. **A IA usa o sistema** (entrada): agentes de IA, como assistentes corporativos, copilotos e automações, consultam e operam os chamados pela API REST, por webhooks e por um servidor **MCP** (Model Context Protocol).

## Princípios

| Princípio | Na prática |
|-----------|------------|
| **Humano no controle** | Por padrão a IA **sugere** e o agente humano confirma. Aplicar automaticamente é opcional, por funcionalidade (`ai_features.auto_apply`) e com limite mínimo de confiança. |
| **API genérica, sem código por modelo** | Um único cliente HTTP no formato compatível com OpenAI (`/chat/completions` e `/embeddings`). A empresa configura **URL base, chave e nome do modelo**, e só isso. Funciona com qualquer serviço que fale esse formato: nuvem, gateway corporativo (ex.: LiteLLM) ou modelo local. Nenhum SDK de fornecedor nem nome de modelo no código. Ver [ADR 0004](adr/0004-ia-api-generica-e-assistiva.md). |
| **Degradável** | Falha, lentidão ou desligamento da IA não bloqueia nenhum fluxo. Chamadas pesadas são assíncronas (worker); as síncronas têm timeout curto. |
| **Privacidade (LGPD)** | Mascaramento de dados pessoais antes do envio, categorias marcadas como `ai_allowed = false` nunca saem para a IA, e é preciso verificar o contrato do serviço de IA escolhido pela empresa (retenção zero, sem uso para treino). Para dados sensíveis, basta apontar a URL para um modelo local. |
| **Auditável e mensurável** | Toda execução é registrada em `ai_runs`: modelo, versão do prompt, tokens, latência, custo e feedback do humano. |
| **Prompts versionados** | Prompts ficam no repositório (`src/chamados/modules/ai/prompts/`), com versão e testes de avaliação. |

## Casos de uso — o sistema usa IA

| # | Funcionalidade | Gatilho | Entrada | Saída (estruturada) | Bloco |
|---|----------------|---------|---------|---------------------|------|
| 1 | **Classificação / triagem** | `ticket.created` (assíncrono) | Título, descrição, árvore de categorias com descrições | `{category_id, team_id, confidence, rationale}` | 1 |
| 2 | **Resumo** | Sob demanda; automático em chamados com > N comentários ou em transferências | Chamado + comentários | `{summary, current_state, next_steps}` | 1 |
| 3 | **Sugestão de resposta** | Botão na tela do agente | Chamado + artigos e chamados resolvidos semelhantes (RAG) | Rascunho de resposta + fontes citadas | 1 |
| 4 | **Chamados semelhantes / duplicados** | `ticket.created` | Embedding do chamado | Lista de chamados com similaridade | 1 |
| 5 | **Deflexão no portal** | Enquanto o solicitante digita | Texto parcial | Artigos sugeridos antes de abrir o chamado | 2 |
| 6 | **Rascunho de artigo** | Chamado resolvido marcado como "útil para KB" | Chamado completo | Rascunho de artigo para revisão | 2 |
| 7 | **Sentimento / urgência** | `ticket.created`, `comment_added` | Texto | `{sentiment, urgency_signals}` | 2 |

Toda saída é validada com um schema **Pydantic**. Uma resposta fora do schema conta como erro e não é aplicada.

**Saída estruturada sem depender do modelo:** nem todo serviço compatível suporta `response_format` com JSON Schema. Por isso o padrão é:

1. o prompt pede JSON e inclui o schema esperado;
2. a resposta é extraída e validada com Pydantic;
3. se a validação falhar, uma nova tentativa envia o erro de validação de volta ao modelo;
4. se falhar de novo, a execução é registrada como `error` e nada é aplicado.

Se o endpoint suportar `response_format` com JSON Schema, o administrador pode ligar essa opção (`settings.json_schema_mode`) para mais confiabilidade.

## Arquitetura do módulo `ai`

```
modules/ai/
├── client.py             # cliente HTTP genérico (httpx): chat(), chat_json(schema), embed()
│                         #   POST {base_url}/chat/completions · POST {base_url}/embeddings
│                         #   timeout, retentativas com backoff, contagem de tokens se informada
├── features/
│   ├── classify.py       # monta o contexto, chama o cliente, valida, grava ai_run, gera a sugestão
│   ├── summarize.py
│   ├── suggest_reply.py
│   └── similar.py
├── redaction.py          # mascaramento de dados pessoais (CPF, e-mail, telefone, cartões etc.)
├── retrieval.py          # busca híbrida: tsvector + pgvector, com fusão de rankings (RRF)
├── prompts/              # templates versionados (ex.: classify.v1.md)
├── evals/                # conjuntos de teste e métricas de qualidade por prompt
└── service.py            # orquestra: checa ai_allowed, feature habilitada, cota e custo
```

**Fluxo de classificação (exemplo):**

```
ticket.created → outbox → worker: ai.classify_ticket
   ├─ categoria/fila permite IA?   não → fim
   ├─ redaction(título, descrição)
   ├─ client.chat_json(prompt classify.v1, schema ClassifyResult)
   ├─ grava ai_runs (entrada mascarada, saída, tokens, latência)
   └─ confiança ≥ min_confidence e auto_apply?
         sim → aplica e registra ticket_event(actor_kind='ai')
         não → cria sugestão visível ao agente (aceitar / editar / rejeitar)
```

## Casos de uso — a IA usa o sistema

### API REST + tokens de API (**feito**)

Qualquer agente de IA opera o sistema pela [API](05-api.md) com um token de API ([docs/05](05-api.md#tokens-de-api)):

- o token age **em nome de uma pessoa**, que o cria na tela **Tokens de API** (menu do usuário) com escopo `read` ou `write`; o que ele faz aparece no histórico como dela, com `via: "api"`;
- nenhum token entra na administração, nem o de um administrador;
- `Idempotency-Key` nos `POST` (opcional, recomendado para agentes): repetir a chamada não registra de novo.

**Ainda não:** contas de serviço (`actor_kind = ai`, um "Assistente Virtual" com identidade própria), escopos mais finos e limite de requisições por token.

**Exemplos:** um assistente no Teams ou Slack que abre chamados a partir de uma conversa, um agente que consulta o status para o colaborador, uma automação que fecha chamados de monitoramento resolvidos.

### Servidor MCP (**feito**)

Expõe o sistema como ferramentas para clientes MCP (Claude Code, IDEs, plataformas de agentes), em `/mcp` (Streamable HTTP, sem estado), com o mesmo token de API no cabeçalho `Authorization`. Estrutura em [ARCHITECTURE 3.14](../ARCHITECTURE.md#314-servidor-mcp-modulesmcp_server).

| Ferramenta MCP | Faz | Equivale a |
|----------------|-----|------------|
| `list_tickets` | Lista com fila, status, grupo, "só meus" e busca | `GET /tickets` |
| `get_ticket` | Chamado completo com as tarefas e as ações permitidas | `GET /tickets/{id}` + `/comments` |
| `get_ticket_history` | Histórico | `GET /tickets/{id}/events` |
| `list_options` | Status e grupos (com membros): os ids que as outras pedem | `GET /statuses`, `GET /teams` |
| `search_clients` | Clientes ativos pelo nome | `GET /clients/options` |
| `create_ticket` | Registra (com `request_id`) | `POST /tickets` |
| `add_task` | Registra uma tarefa, com o tempo gasto (com `request_id`) | `POST /tickets/{id}/comments` |
| `change_status` | Muda o status (qualquer um que a pessoa possa escolher, menos um cancelado: para isso, `cancel_ticket`) | `PATCH /tickets/{id}` com `status_id` |
| `assign_ticket` | Atribui: `main` troca o responsável principal (`"me"` assume), `add` acrescenta mais um | `POST /tickets/{id}/assign`, `PUT /tickets/{id}/assignees` |
| `transfer_ticket` | Transfere para outro grupo, com um responsável de lá e o motivo | `POST /tickets/{id}/transfer` |
| `cancel_ticket` | Cancela, com o motivo opcional (`destructiveHint`; as instruções pedem a confirmação da pessoa) | `POST /tickets/{id}/transitions` (`cancel`) |

- As ferramentas são uma camada fina sobre os **services** (mesmas permissões, mesma auditoria); o histórico marca `via: "mcp"`.
- As de leitura levam `readOnlyHint`, para o cliente poder dispensar a confirmação; as de escrita, não.
- As instruções do servidor dizem ao modelo que o texto dos chamados é dado, nunca instrução (prompt injection).
- O `get_ticket` não conta como visita da pessoa: o aviso de novidade continua para ela.
- **Fora, por enquanto:** concluir e reabrir pelo fluxo (com código de resolução), observadores, anexos, `stdio` (uso local sem rede) e a base de conhecimento (ainda não existe). O Claude Desktop e o claude.ai só aceitam servidores MCP remotos com OAuth; com token no cabeçalho, o caminho hoje é o Claude Code ou outro cliente que aceite cabeçalhos.

### Webhooks

Agentes externos podem reagir a eventos (`ticket.created`, `ticket.comment_added`…) sem polling. Ver [API → Webhooks](05-api.md#webhooks-de-saída-futuro).

## Segurança específica de IA

| Risco | Mitigação |
|-------|-----------|
| **Prompt injection** (texto do chamado tenta manipular a IA) | O conteúdo do usuário vai sempre delimitado como *dado*, nunca como instrução; as saídas são estruturadas e validadas; a IA de triagem não tem ferramentas com efeito colateral; ações automáticas são limitadas a um conjunto fechado (categoria, fila) |
| **Vazamento de dados** | Mascaramento, `ai_allowed` por categoria, opção de modelo local, a RAG respeita a visibilidade (o solicitante nunca recebe trechos de notas internas ou de chamados de outras pessoas) |
| **Agente externo com permissão demais** | Escopos mínimos, sem `admin`, conta de serviço dedicada, revogação imediata, auditoria |
| **Custo descontrolado** | Cota mensal de tokens por funcionalidade, alerta de consumo, cache de resumos (só regenera se o chamado mudou) |
| **Alucinação na resposta** | A sugestão de resposta cita as fontes (artigos e chamados); o humano revisa antes de enviar; o feedback é medido |

## Métricas de qualidade

- **Classificação:** acurácia contra a categoria final, medida após o fechamento do chamado
- **Sugestões:** taxa de aceitação (aceita / editada / rejeitada)
- **Duplicados:** precisão das sugestões marcadas como duplicadas
- **Operação:** latência p95, taxa de erro e tokens por chamado, por endpoint e modelo configurado

Esses dados alimentam um painel em `/admin/ai` e permitem comparar modelos (trocando só a configuração) e versões de prompt (teste A/B).
