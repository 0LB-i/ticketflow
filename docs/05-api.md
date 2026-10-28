# 5. API

A API REST é o **contrato principal** do sistema. Na v1.0 o único cliente é a interface web; depois, integrações e agentes de IA vão usar a mesma API. A especificação OpenAPI 3.1 é gerada pelo FastAPI e publicada em `/api/docs` e `/api/openapi.json`.

## Convenções

| Tema | Convenção |
|------|-----------|
| Base | `/api/v1` |
| Formato | JSON, `snake_case`, datas ISO 8601 com fuso (`2026-10-09T14:30:00-03:00`) |
| Identificadores | `public_id` (UUID) em todas as respostas; o número do chamado também é aceito: `/tickets/1234` ou `/tickets/{uuid}` |
| Paginação | Por cursor: `?limit=50&cursor=...` → `{"items": [...], "next_cursor": "..."}` |
| Filtros | Query string: `?status=open&team=ti&q=impressora` |
| Ordenação | `?sort=-created_at` |
| Erros | RFC 9457 (Problem Details): `{"type", "title", "status", "detail", "errors": [...]}` |
| Idioma | Mensagens (`title`, `detail`) em português ou inglês, conforme o header `Accept-Language` (nas telas, o idioma da pessoa). As mensagens são escritas em português e traduzidas pelo catálogo em `core/i18n.py` |
| Idempotência | Header `Idempotency-Key` (até 255 caracteres) em `POST` com token de API: a primeira resposta de sucesso volta igual, com `Idempotent-Replayed: true`, sem executar de novo; mesma chave com outro corpo, 422; a primeira ainda em andamento, 409. Vale por pelo menos 24 h, por token. Opcional, mas recomendado para agentes de IA, que repetem chamadas |
| Concorrência | `ETag` / `If-Match` em `PATCH` para evitar sobrescrever alteração de outro usuário. O `GET /tickets/{id}` e o `PATCH` devolvem o header `ETag` (também no campo `etag`), que só muda quando um campo que o `PATCH` altera muda. Com `If-Match` desatualizado, **412**; sem `If-Match`, o `PATCH` grava como antes |
| Versionamento | Mudanças incompatíveis só em uma nova versão (`/api/v2`); campos novos são aditivos |
| Rate limit | Headers `RateLimit-*`; `429` com `Retry-After` |
| CORS | Desnecessário: as telas são servidas na mesma origem da API |

## Autenticação

| Cliente | Mecanismo |
|---------|-----------|
| Interface web (telas do servidor) | Sessão via cookie `HttpOnly` + `Secure` + `SameSite=Lax` + token CSRF num campo escondido do formulário ou no header (HTMX e envio de anexos). Nenhum token fica no `localStorage` |
| Integrações e agentes de IA | `Authorization: Bearer <token>`, um token de API com escopo `read` ou `write` (abaixo) |

### Tokens de API

Desde 2026-10-23 (migração `0032`). Um token sempre age **em nome de um usuário**: passa pelas mesmas permissões e pela mesma visibilidade dele, e o que faz aparece no histórico e na auditoria como dele. Cada pessoa cria e revoga os próprios na tela **Tokens de API** (menu do usuário, `/meus-tokens`) ou por `GET`/`POST /me/tokens` e `DELETE /me/tokens/{id}` (só com a sessão da interface; o valor vem uma vez, no campo `token` da criação; validade de 1 a 365 dias, padrão 90). Quem tem `admin.users` vê os tokens ativos de todos e revoga qualquer um na tela **Administração → Tokens de API** (`/admin/tokens`) ou por `GET /admin/api-tokens` e `DELETE /admin/api-tokens/{id}` (nenhum token entra nessas rotas). Quem administra o servidor também pode usar o comando `chamados token` ([ARCHITECTURE 3.10](../ARCHITECTURE.md#310-comando-chamados-clipy)).

```
Authorization: Bearer tf_...
```

| Escopo | Permite |
|--------|---------|
| `read` | Só `GET`: listar e ler chamados, tarefas, histórico, anexos, opções dos formulários |
| `write` | Também criar e alterar chamados, comentar, anexar |

- **Fora da administração:** as rotas que exigem uma permissão de administração respondem 403 a qualquer token, mesmo o de um administrador: usuários, tokens de todos, a gestão de grupos, categorias, status e códigos de resolução (criar, alterar, ordenar, remover), configurações, auditoria e o cadastro de clientes. As leituras abertas a qualquer pessoa logada continuam: `GET /teams` (sem os e-mails dos membros), `/categories`, `/statuses`, `/resolution-codes`, `/clients/options`, `/work-hours`.
- **Só pela interface:** sair e trocar a senha (403 com token).
- Token inválido, revogado, vencido ou de usuário inativo/excluído: 401. Desativar ou excluir a pessoa revoga os tokens dela: reativar a conta não os traz de volta. Requisições com token não usam cookie nem CSRF.

**Depois:** escopos mais finos (`tickets:read`, `kb:write`…), contas de serviço (`actor_kind = api_client` ou `ai`).

## Endpoints (primeira versão)

### Chamados

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/tickets` | Listar e filtrar: fila (`view`: `mine`, `waiting`, `watching`, `all`), `team`, `assignee` (`me` ou o id), `status` e a busca textual `q` |
| `GET` | `/tickets/counts` | Quantos chamados há em cada fila (os contadores das abas) |
| `POST` | `/tickets` | Registrar chamado: `assignee` (`"me"` ou um membro do grupo) e `client_id` são obrigatórios |
| `GET` | `/tickets/{id}` | Detalhe |
| `PATCH` | `/tickets/{id}` | Alterar campos (título, categoria, cliente e contato, tags) |
| `POST` | `/tickets/{id}/transitions` | Mudar status pelo fluxo: `{"action": "close", "comment": "...", "resolution_code_id": ...}`. Ações: `wait`, `resume`, `close`, `reopen`, `cancel` ([10.5](10-chamados.md#105-status-e-fluxo)); o comentário vira comentário do chamado |
| `GET` | `/tickets/{id}/comments` | Listar comentários |
| `POST` | `/tickets/{id}/comments` | Comentar: `{"body", "mention_ids": [...], "attachment_ids": [...]}`. Os `@mencionados` vão em `mention_ids` (o editor os escolhe numa lista) e viram observadores |
| `PATCH` | `/tickets/{id}/comments/{cid}` | Editar o próprio comentário, por até 10 minutos |
| `GET` | `/tickets/{id}/events` | Histórico / linha do tempo |
| `PUT` / `DELETE` | `/tickets/{id}/watchers/{user_id}` | Observadores (respondem `204`: quem se retira de um chamado de outro grupo deixa de vê-lo) |
| `POST` | `/tickets/{id}/links` | Vincular chamados |
| `POST` | `/tickets/{id}/assign` | Assumir (`{"assignee": "me"}`) ou atribuir (id de um membro do grupo); o chamado nunca fica sem responsável |
| `PUT` | `/tickets/{id}/assignees` | Vários responsáveis (ou o grupo todo): `{"assignee_ids": [...]}`, a lista inteira; quem entra é membro ativo do grupo (quem já estava e saiu do grupo pode ficar ou sair); o principal continua se estiver nela, senão o primeiro assume |
| `POST` | `/tickets/{id}/transfer` | Transferir: `{"team_id", "assignee_id", "reason"}`; o novo responsável é um membro ativo do grupo de destino |
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
| `POST` | `/uploads` | Envia um arquivo (1ª etapa, multipart, campo `file`). Ver [11.4](11-anexos-e-arquivos.md#114-fluxo-de-envio-em-duas-etapas). O vínculo vem depois, em `attachment_ids` no registro, no comentário (e na edição dele), na mudança de status e no `PATCH` do chamado (imagens da descrição) |
| `GET` | `/attachments/{id}` | Baixa (verifica permissão). O detalhe do chamado lista os anexos em `attachments` |
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
| `GET` | `/branding` | **Pública** (a tela de login usa): idioma padrão, as 3 cores (`null` = padrão) e os endereços do logotipo e do logotipo dos relatórios |
| `GET` | `/branding/logo` | Imagem do logotipo (endereço versionado, guardado em cache pelo navegador) |
| `GET` | `/branding/report-logo` | Imagem do logotipo dos relatórios (PDFs e prévia do relatório para o cliente), como a do logotipo |
| `PATCH` | `/admin/settings` | `{"default_locale": "pt-BR" \| "en", "colors": {"brand", "neutral", "background"} \| null}` (`admin.settings`) |
| `PUT` / `DELETE` | `/admin/settings/logo` | Envia (`{"data_url": "data:image/png;base64,..."}`, PNG, JPEG ou WebP até 256 KB) ou remove o logotipo |
| `PUT` / `DELETE` | `/admin/settings/report-logo` | O mesmo, para o logotipo dos relatórios, separado do logotipo do aplicativo |
| `PATCH` | `/me` | Preferências da pessoa: `{"locale": "en" \| "pt-BR" \| null}` (nulo segue o padrão do sistema) |

### Demais recursos

`/auth/*` e `/me` (ver [Login e autenticação](09-login-e-autenticacao.md#99-endpoints)), `/users`, `/teams`, `/roles`, `/categories`, `/statuses`, `/resolution-codes`, `/notifications`, `/kb/articles`, `/reports/*`, `/admin/audit-log`, `/admin/settings`

No `GET /reports`, cada linha de `clients` traz também o plano do contrato do cliente: `in_plan_minutes` e `excess_minutes` (`minutes` é a soma dos dois; sem plano mensal ou anual, tudo é excedente). O CSV `clients` tem as mesmas colunas, no fim. As horas descontadas da aba Clientes são só da tela.

Futuro: `/saved-views`, `/admin/idp-mappings`, `/admin/api-clients`, `/admin/webhooks`, `/admin/ai`

## Webhooks de saída (futuro)

**Eventos:** `ticket.created`, `ticket.updated`, `ticket.status_changed`, `ticket.assigned`, `ticket.assignees_changed`, `ticket.transferred`, `ticket.approval_requested`, `ticket.approval_decided`, `ticket.comment_added`, `ticket.closed`, `ticket.reopened`

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
  "beneficiary_name": "João Silva",
  "assignee": "me"
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
