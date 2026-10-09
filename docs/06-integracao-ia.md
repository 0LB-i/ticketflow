# 6. Integração com IA

A integração acontece em **duas direções**:

1. **O sistema usa IA** (saída): chama modelos de linguagem e de embeddings para classificar, resumir, sugerir respostas e encontrar chamados semelhantes.
2. **A IA usa o sistema** (entrada): agentes de IA, como assistentes corporativos, copilotos e automações, consultam e operam os chamados pela API REST, por webhooks e por um servidor **MCP** (Model Context Protocol).

## Princípios

| Princípio | Na prática |
|-----------|------------|
| **Humano no controle** | Por padrão a IA **sugere** e o agente humano confirma. Aplicar automaticamente é opcional, por funcionalidade (`ai_features.auto_apply`) e com limite mínimo de confiança. |
| **Agnóstico de provedor** | Interface única `AIProvider` com adaptadores: Anthropic (Claude), OpenAI, Azure OpenAI, APIs compatíveis com OpenAI e modelos locais (Ollama / vLLM) para dados sensíveis. Provedor e modelo são configuráveis por funcionalidade. |
| **Degradável** | Falha, lentidão ou desligamento da IA não bloqueia nenhum fluxo. Chamadas pesadas são assíncronas (worker); as síncronas têm timeout curto. |
| **Privacidade (LGPD)** | Mascaramento de dados pessoais antes do envio, categorias marcadas como `ai_allowed = false` nunca saem para a IA, e é preciso verificar o contrato do provedor (retenção zero, sem uso para treino). |
| **Auditável e mensurável** | Toda execução é registrada em `ai_runs`: modelo, versão do prompt, tokens, latência, custo e feedback do humano. |
| **Prompts versionados** | Prompts ficam no repositório (`src/chamados/modules/ai/prompts/`), com versão e testes de avaliação. |

## Casos de uso — o sistema usa IA

| # | Funcionalidade | Gatilho | Entrada | Saída (estruturada) | Fase |
|---|----------------|---------|---------|---------------------|------|
| 1 | **Classificação / triagem** | `ticket.created` (assíncrono) | Título, descrição, árvore de categorias com descrições | `{category_id, priority, team_id, confidence, rationale}` | 3 |
| 2 | **Resumo** | Sob demanda; automático em chamados com > N comentários ou em transferências | Chamado + comentários | `{summary, current_state, next_steps}` | 3 |
| 3 | **Sugestão de resposta** | Botão na tela do agente | Chamado + artigos e chamados resolvidos semelhantes (RAG) | Rascunho de resposta + fontes citadas | 3 |
| 4 | **Chamados semelhantes / duplicados** | `ticket.created` | Embedding do chamado | Lista de chamados com similaridade | 3 |
| 5 | **Deflexão no portal** | Enquanto o solicitante digita | Texto parcial | Artigos sugeridos antes de abrir o chamado | 4 |
| 6 | **Rascunho de artigo** | Chamado resolvido marcado como "útil para KB" | Chamado completo | Rascunho de artigo para revisão | 4 |
| 7 | **Sentimento / urgência** | `ticket.created`, `comment_added` | Texto | `{sentiment, urgency_signals}` | 4 |

Toda saída é validada com um schema **Pydantic**. Uma resposta fora do schema conta como erro e não é aplicada.

## Arquitetura do módulo `ai`

```
modules/ai/
├── providers/
│   ├── base.py           # Protocol AIProvider: complete(), complete_structured(), embed()
│   ├── anthropic.py
│   ├── openai.py         # também cobre Azure e APIs compatíveis com OpenAI (vLLM, LM Studio)
│   └── ollama.py
├── features/
│   ├── classify.py       # monta o contexto, chama o provedor, valida, grava ai_run, gera a sugestão
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
   ├─ provider.complete_structured(prompt classify.v1, schema ClassifyResult)
   ├─ grava ai_runs (entrada mascarada, saída, tokens, latência)
   └─ confiança ≥ min_confidence e auto_apply?
         sim → aplica e registra ticket_event(actor_kind='ai')
         não → cria sugestão visível ao agente (aceitar / editar / rejeitar)
```

## Casos de uso — a IA usa o sistema

### API REST + tokens com escopo

Qualquer agente de IA pode operar o sistema pela [API](05-api.md) com um token do tipo `ai_agent`:

- escopos mínimos (ex.: `tickets:read`, `tickets:write`, sem `tickets:internal`);
- age em nome de uma **conta de serviço** identificada (ex.: "Assistente Virtual"), e tudo aparece na auditoria como `actor_kind = ai`;
- `Idempotency-Key` obrigatório para escrita;
- rate limit próprio.

**Exemplos:** um assistente no Teams ou Slack que abre chamados a partir de uma conversa, um agente que consulta o status para o colaborador, uma automação que fecha chamados de monitoramento resolvidos.

### Servidor MCP (Fase 4)

Expõe o sistema como ferramentas para clientes MCP (Claude Desktop, Claude Code, IDEs, plataformas de agentes):

| Ferramenta MCP | Mapeia para |
|----------------|-------------|
| `search_tickets` | `GET /tickets/search` |
| `get_ticket` | `GET /tickets/{id}` (com comentários e resumo) |
| `create_ticket` | `POST /tickets` |
| `add_comment` | `POST /tickets/{id}/comments` |
| `update_ticket_status` | `POST /tickets/{id}/transitions` |
| `search_knowledge_base` | `GET /kb/articles?q=` |

O servidor MCP é uma camada fina sobre os **services** (mesmas permissões e a mesma auditoria), autenticada por token de API. Transporte: *Streamable HTTP* para uso remoto e `stdio` para uso local.

### Webhooks

Agentes externos podem reagir a eventos (`ticket.created`, `ticket.comment_added`…) sem polling. Ver [API → Webhooks](05-api.md#webhooks-de-saída).

## Segurança específica de IA

| Risco | Mitigação |
|-------|-----------|
| **Prompt injection** (texto do chamado tenta manipular a IA) | O conteúdo do usuário vai sempre delimitado como *dado*, nunca como instrução; as saídas são estruturadas e validadas; a IA de triagem não tem ferramentas com efeito colateral; ações automáticas são limitadas a um conjunto fechado (categoria, prioridade, fila) |
| **Vazamento de dados** | Mascaramento, `ai_allowed` por categoria, opção de modelo local, a RAG respeita a visibilidade (o solicitante nunca recebe trechos de notas internas ou de chamados de outras pessoas) |
| **Agente externo com permissão demais** | Escopos mínimos, sem `admin`, conta de serviço dedicada, revogação imediata, auditoria |
| **Custo descontrolado** | Cota mensal de tokens por funcionalidade, alerta de custo, cache de resumos (só regenera se o chamado mudou) |
| **Alucinação na resposta** | A sugestão de resposta cita as fontes (artigos e chamados); o humano revisa antes de enviar; o feedback é medido |

## Métricas de qualidade

- **Classificação:** acurácia contra a categoria final, medida após o fechamento do chamado
- **Sugestões:** taxa de aceitação (aceita / editada / rejeitada)
- **Duplicados:** precisão das sugestões marcadas como duplicadas
- **Operação:** latência p95, taxa de erro e custo por chamado, por provedor e modelo

Esses dados alimentam um painel em `/admin/ai` e permitem comparar provedores e versões de prompt (teste A/B).
