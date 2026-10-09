# 5. API

A API REST é o **contrato principal** do sistema: interface web, integrações e agentes de IA usam a mesma API. A especificação OpenAPI 3.1 é gerada pelo FastAPI e publicada em `/api/docs` e `/api/openapi.json`.

## Convenções

| Tema | Convenção |
|------|-----------|
| Base | `/api/v1` |
| Formato | JSON, `snake_case`, datas ISO 8601 com fuso (`2026-10-09T14:30:00-03:00`) |
| Identificadores | `public_id` (UUID) em todas as respostas; o número do chamado também é aceito: `/tickets/1234` ou `/tickets/{uuid}` |
| Paginação | Por cursor: `?limit=50&cursor=...` → `{"items": [...], "next_cursor": "..."}` |
| Filtros | Query string: `?status=open&team=ti&priority_gte=3&q=impressora` |
| Ordenação | `?sort=-created_at,priority` |
| Erros | RFC 9457 (Problem Details): `{"type", "title", "status", "detail", "errors": [...]}` |
| Idempotência | Header `Idempotency-Key` aceito em `POST`, essencial para agentes de IA que repetem chamadas |
| Concorrência | `ETag` / `If-Match` em `PATCH` para evitar sobrescrever alteração de outro usuário |
| Versionamento | Mudanças incompatíveis só em uma nova versão (`/api/v2`); campos novos são aditivos |
| Rate limit | Headers `RateLimit-*`; `429` com `Retry-After` |
| CORS | Desnecessário em produção: a SPA é servida na mesma origem da API. Em desenvolvimento, o proxy do Vite encaminha `/api` |

## Autenticação

| Cliente | Mecanismo |
|---------|-----------|
| Interface web (SPA Vue) | Sessão via cookie `HttpOnly` + `Secure` + `SameSite=Lax` + token CSRF enviado em header (após login local ou OIDC). Nenhum token fica no `localStorage` |
| Integrações e agentes de IA | `Authorization: Bearer <token>`, um token de API com **escopos** |

**Escopos:**

| Escopo | Permite |
|--------|---------|
| `tickets:read` | Listar e ler chamados (respeitando a visibilidade do usuário que o token representa) |
| `tickets:write` | Criar e alterar chamados, comentar |
| `tickets:internal` | Ler e escrever notas internas |
| `kb:read` / `kb:write` | Base de conhecimento |
| `users:read` | Consultar usuários (dados mínimos) |
| `admin` | Configuração (nunca concedido a agentes de IA) |

Um token de API sempre age **em nome de** um usuário (`acts_as_user_id`) ou de uma conta de serviço. Assim toda ação passa pelas mesmas regras de permissão e aparece na auditoria como `actor_kind = api_client` ou `ai`.

## Endpoints (primeira versão)

### Chamados

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/tickets` | Listar e filtrar |
| `POST` | `/tickets` | Abrir chamado |
| `GET` | `/tickets/{id}` | Detalhe |
| `PATCH` | `/tickets/{id}` | Alterar campos (título, prioridade, categoria, equipe, responsável, tags) |
| `POST` | `/tickets/{id}/transitions` | Mudar status: `{"to": "resolved", "comment": "..."}` |
| `GET` | `/tickets/{id}/comments` | Listar comentários |
| `POST` | `/tickets/{id}/comments` | Comentar: `{"body", "visibility": "public" \| "internal", "attachment_ids": [...]}` |
| `GET` | `/tickets/{id}/events` | Histórico / linha do tempo |
| `PUT` / `DELETE` | `/tickets/{id}/watchers/{user_id}` | Observadores |
| `POST` | `/tickets/{id}/links` | Vincular chamados |
| `POST` | `/tickets/{id}/satisfaction` | Avaliar atendimento |
| `GET` | `/tickets/search` | Busca textual e/ou semântica: `?q=...&mode=text\|semantic\|hybrid` |
| `POST` | `/tickets/{id}/assign` | Assumir (`{"assignee": "me"}`) ou atribuir |
| `POST` | `/tickets/{id}/transfer` | Transferir: `{"team_id", "reason"}` |
| `POST` | `/tickets/next` | "Pegar o próximo" da fila |
| `POST` | `/tickets/{id}/merge` | Mesclar em outro chamado |
| `GET` / `POST` | `/tickets/{id}/approvals` | Aprovações do chamado |
| `POST` | `/approvals/{id}/decision` | `{"decision": "approve" \| "reject", "comment"}` |
| `GET` | `/approvals?status=pending` | Aprovações pendentes do usuário |
| `POST` | `/tickets/{id}/comments/{cid}/hide` | Ocultar comentário (com motivo) |

O detalhe do chamado inclui `allowed_actions` (ex.: `["comment", "assign_self", "transfer", "resolve"]`), calculado pelo backend, para a interface decidir quais botões mostrar.

### Anexos

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/uploads` | Envia um arquivo (1ª etapa). Ver [11.4](11-anexos-e-arquivos.md#114-fluxo-de-envio-em-duas-etapas) |
| `GET` | `/attachments/{id}` | Baixa (verifica permissão) |
| `POST` | `/attachments/{id}/hide` | Oculta (com motivo) |

### IA

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/tickets/{id}/ai/summary` | Gerar ou obter resumo |
| `POST` | `/tickets/{id}/ai/suggest-reply` | Sugestão de resposta para o agente |
| `GET` | `/tickets/{id}/ai/suggestions` | Sugestões pendentes (classificação, duplicados) |
| `POST` | `/ai/suggestions/{run_id}/feedback` | `{"feedback": "accepted" \| "edited" \| "rejected"}` |
| `GET` | `/tickets/{id}/similar` | Chamados semelhantes (busca vetorial) |

### Demais recursos

`/auth/*` e `/me` (ver [Login e autenticação](09-login-e-autenticacao.md#99-endpoints)), `/users`, `/departments`, `/teams`, `/roles`, `/categories`, `/statuses`, `/resolution-codes`, `/canned-responses`, `/saved-views`, `/notifications`, `/sla-policies`, `/calendars`, `/kb/articles`, `/reports/*`, `/admin/audit-log`, `/admin/idp-mappings`, `/admin/settings`, `/admin/api-clients`, `/admin/webhooks`, `/admin/ai`

## Webhooks de saída

**Eventos:** `ticket.created`, `ticket.updated`, `ticket.status_changed`, `ticket.assigned`, `ticket.transferred`, `ticket.approval_requested`, `ticket.approval_decided`, `ticket.comment_added`, `ticket.sla_warning`, `ticket.sla_breached`, `ticket.resolved`, `ticket.closed`

**Entrega:**

```http
POST https://destino.exemplo/webhook
Content-Type: application/json
X-Chamados-Event: ticket.created
X-Chamados-Delivery: 0b9c...-uuid
X-Chamados-Timestamp: 1791561600
X-Chamados-Signature: sha256=<HMAC-SHA256(secret, timestamp + "." + body)>

{
  "id": "0b9c...-uuid",
  "type": "ticket.created",
  "occurred_at": "2026-10-09T14:30:00-03:00",
  "data": { "ticket": { "id": "...", "number": 1234, "title": "...", "...": "..." } }
}
```

- Novas tentativas com backoff exponencial por até 24 h; a assinatura é desativada após falhas consecutivas
- O receptor deve tratar a entrega como **pelo menos uma vez** e deduplicar pelo `id`
- Webhooks permitem conectar o sistema a plataformas de automação (n8n, Make, Power Automate) e a agentes de IA externos sem polling

## Exemplo: abrir um chamado

```http
POST /api/v1/tickets
Authorization: Bearer chm_live_3f9a...
Idempotency-Key: 6c1e7c1a-...
Content-Type: application/json

{
  "title": "Impressora do 3º andar não imprime",
  "description": "Desde hoje cedo aparece 'offline'.",
  "category_id": "b6f1...",
  "priority": 2,
  "custom_fields": { "patrimonio": "IMP-0042" }
}
```

```http
HTTP/1.1 201 Created
Location: /api/v1/tickets/7d2e...

{
  "id": "7d2e...",
  "number": 1234,
  "status": { "name": "Novo", "kind": "new" },
  "team": { "id": "...", "name": "TI - Suporte" },
  "sla": { "first_response_due_at": "2026-10-09T16:30:00-03:00" },
  "...": "..."
}
```
