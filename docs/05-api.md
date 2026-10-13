# 5. API

A API REST é o **contrato principal** do sistema. Na v1.0 o único cliente é a interface web; depois, integrações e agentes de IA vão usar a mesma API. A especificação OpenAPI 3.1 é gerada pelo FastAPI e publicada em `/api/docs` e `/api/openapi.json`.

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
| Idioma | Mensagens (`title`, `detail`) em português ou inglês, conforme o header `Accept-Language` que a interface envia com o idioma escolhido. As mensagens são escritas em português e traduzidas pelo catálogo em `core/i18n.py` |
| Idempotência | Header `Idempotency-Key` em `POST` (futuro, junto com os tokens de API: essencial para agentes de IA que repetem chamadas) |
| Concorrência | `ETag` / `If-Match` em `PATCH` para evitar sobrescrever alteração de outro usuário |
| Versionamento | Mudanças incompatíveis só em uma nova versão (`/api/v2`); campos novos são aditivos |
| Rate limit | Headers `RateLimit-*`; `429` com `Retry-After` |
| CORS | Desnecessário em produção: a SPA é servida na mesma origem da API. Em desenvolvimento, o proxy do Vite encaminha `/api` |

## Autenticação

| Cliente | Mecanismo |
|---------|-----------|
| Interface web (SPA Vue) | Sessão via cookie `HttpOnly` + `Secure` + `SameSite=Lax` + token CSRF enviado em header (após o login). Nenhum token fica no `localStorage` |
| Integrações e agentes de IA (futuro) | `Authorization: Bearer <token>`, um token de API com **escopos** |

### Tokens de API (futuro)

Ficaram para depois da v1.0 (revisão de escopo de 2026-10-09). O desenho fica registrado aqui.

**Escopos:**

| Escopo | Permite |
|--------|---------|
| `tickets:read` | Listar e ler chamados (respeitando a visibilidade do usuário que o token representa) |
| `tickets:write` | Criar e alterar chamados, comentar |
| `kb:read` / `kb:write` | Base de conhecimento |
| `users:read` | Consultar usuários (dados mínimos) |
| `admin` | Configuração (nunca concedido a agentes de IA) |

Um token de API sempre age **em nome de** um usuário (`acts_as_user_id`) ou de uma conta de serviço. Assim toda ação passa pelas mesmas regras de permissão e aparece na auditoria como `actor_kind = api_client` ou `ai`.

## Endpoints (primeira versão)

### Chamados

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/tickets` | Listar e filtrar: fila (`view`: `unassigned`, `mine`, `news`, `waiting`, `watching`, `all`), `team`, `assignee`, `status`, `priority` e a busca textual `q` |
| `GET` | `/tickets/counts` | Quantos chamados há em cada fila (os contadores das abas) |
| `POST` | `/tickets` | Registrar chamado |
| `GET` | `/tickets/{id}` | Detalhe |
| `PATCH` | `/tickets/{id}` | Alterar campos (título, prioridade, categoria, setor e pessoa atendidos, tags) |
| `POST` | `/tickets/{id}/transitions` | Mudar status pelo fluxo: `{"action": "close", "comment": "...", "resolution_code_id": ...}`. Ações: `wait`, `resume`, `close`, `reopen`, `cancel` ([10.5](10-chamados.md#105-status-e-fluxo)); o comentário vira comentário do chamado |
| `GET` | `/tickets/{id}/comments` | Listar comentários |
| `POST` | `/tickets/{id}/comments` | Comentar: `{"body", "mention_ids": [...], "attachment_ids": [...]}`. Os `@mencionados` vão em `mention_ids` (o editor os escolhe numa lista) e viram observadores |
| `PATCH` | `/tickets/{id}/comments/{cid}` | Editar o próprio comentário, por até 10 minutos |
| `GET` | `/tickets/{id}/events` | Histórico / linha do tempo |
| `PUT` / `DELETE` | `/tickets/{id}/watchers/{user_id}` | Observadores (respondem `204`: quem se retira de um chamado de outro grupo deixa de vê-lo) |
| `POST` | `/tickets/{id}/links` | Vincular chamados |
| `POST` | `/tickets/{id}/assign` | Assumir (`{"assignee": "me"}`), atribuir (id de um membro do grupo) ou devolver à fila (`null`) |
| `POST` | `/tickets/{id}/transfer` | Transferir: `{"team_id", "reason"}` |
| `POST` | `/tickets/next` | "Pegar o próximo" da fila Não atribuídos: `{"team_id"}` opcional; fila vazia responde `404` |
| `POST` | `/tickets/{id}/merge` | Mesclar em outro chamado |
| `GET` / `POST` | `/tickets/{id}/approvals` | Aprovações do chamado |
| `POST` | `/approvals/{id}/decision` | `{"decision": "approve" \| "reject", "comment"}` |
| `GET` | `/approvals?status=pending` | Aprovações pendentes dos grupos que o usuário supervisiona |
| `POST` | `/tickets/{id}/comments/{cid}/hide` | Ocultar comentário (com motivo) |

O detalhe do chamado inclui `allowed_actions` (ex.: `["comment", "assign_self", "transfer", "close"]`), calculado pelo backend, para a interface decidir quais botões mostrar.

Um chamado que o usuário não pode ver responde `403` ("Você não tem acesso a este chamado"); um número inexistente, `404`. Sem `team_id`, `POST /tickets` usa o grupo padrão da categoria (roteamento), que precisa ser um dos grupos do usuário.

### Anexos

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/uploads` | Envia um arquivo (1ª etapa). Ver [11.4](11-anexos-e-arquivos.md#114-fluxo-de-envio-em-duas-etapas) |
| `GET` | `/attachments/{id}` | Baixa (verifica permissão) |
| `POST` | `/attachments/{id}/hide` | Oculta (com motivo) |

### IA (futuro)

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/tickets/{id}/ai/summary` | Gerar ou obter resumo |
| `POST` | `/tickets/{id}/ai/suggest-reply` | Sugestão de resposta para o agente |
| `GET` | `/tickets/{id}/ai/suggestions` | Sugestões pendentes (classificação, duplicados) |
| `POST` | `/ai/suggestions/{run_id}/feedback` | `{"feedback": "accepted" \| "edited" \| "rejected"}` |
| `GET` | `/tickets/{id}/similar` | Chamados semelhantes (busca vetorial) |

### Configurações

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/branding` | **Pública** (a tela de login usa): idioma padrão, as 3 cores (`null` = padrão) e o endereço do logotipo |
| `GET` | `/branding/logo` | Imagem do logotipo (endereço versionado, guardado em cache pelo navegador) |
| `PATCH` | `/admin/settings` | `{"default_locale": "pt-BR" \| "en", "colors": {"brand", "neutral", "background"} \| null}` (`admin.settings`) |
| `PUT` / `DELETE` | `/admin/settings/logo` | Envia (`{"data_url": "data:image/png;base64,..."}`, PNG, JPEG ou WebP até 256 KB) ou remove o logotipo |
| `PATCH` | `/me` | Preferências da pessoa: `{"locale": "en" \| "pt-BR" \| null}` (nulo segue o padrão do sistema) |

### Demais recursos

`/auth/*` e `/me` (ver [Login e autenticação](09-login-e-autenticacao.md#99-endpoints)), `/users`, `/teams`, `/departments` (setores atendidos), `/roles`, `/categories`, `/statuses`, `/resolution-codes`, `/notifications`, `/kb/articles`, `/reports/*`, `/admin/audit-log`, `/admin/settings`

Futuro: `/saved-views`, `/admin/idp-mappings`, `/admin/api-clients`, `/admin/webhooks`, `/admin/ai`

## Webhooks de saída (futuro)

**Eventos:** `ticket.created`, `ticket.updated`, `ticket.status_changed`, `ticket.assigned`, `ticket.transferred`, `ticket.approval_requested`, `ticket.approval_decided`, `ticket.comment_added`, `ticket.closed`, `ticket.reopened`

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
Cookie: session=...
X-CSRF-Token: ...
Content-Type: application/json

{
  "title": "Impressora do 3º andar não imprime",
  "description": "Financeiro avisou por telefone: aparece 'offline'.",
  "team_id": "5a0c...",
  "category_id": "b6f1...",
  "department_id": "9e3d...",
  "beneficiary_name": "João Silva",
  "assignee": "me",
  "urgency": 2,
  "impact": 1
}
```

```http
HTTP/1.1 201 Created
Location: /api/v1/tickets/7d2e...

{
  "id": "7d2e...",
  "number": 1234,
  "status": { "name": "Pendente", "kind": "open" },
  "team": { "id": "...", "name": "TI - Suporte" },
  "...": "..."
}
```
