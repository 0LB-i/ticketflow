# 5. API

A API REST é o **contrato principal** do sistema. A interface web usa as mesmas regras, e outros softwares integram por ela com um token de API. Os assistentes de IA têm também o servidor MCP ([docs/06](06-integracao-ia.md#servidor-mcp-feito)). A especificação OpenAPI 3.1 é gerada pelo FastAPI e publicada em `/api/openapi.json`, ou sai em arquivo por `chamados openapi -o arquivo.json`, para entregar a quem vai integrar. A documentação interativa (Swagger) fica desligada: ela carrega scripts de uma CDN na mesma origem das telas.

## Convenções

| Tema | Convenção |
|------|-----------|
| Base | `/api/v1` |
| Formato | JSON, `snake_case`, datas ISO 8601 com fuso (`2026-10-09T14:30:00-03:00`) |
| Identificadores | `public_id` (UUID) em todas as respostas; o número do chamado também é aceito: `/tickets/1234` ou `/tickets/{uuid}`. Status e códigos de resolução usam um id numérico |
| Paginação | Por cursor: `?limit=50&cursor=...` → `{"items": [...], "next_cursor": "..."}` (`next_cursor` nulo na última página). Na lista de chamados, `limit` vai de 1 a 200 (padrão 50) |
| Filtros | Query string: `?view=mine&status=open&team=<uuid>&q=impressora`; para mais de um valor, repita o parâmetro (`?status=open&status=waiting`) |
| Ordenação | A lista de chamados vem do mais novo para o mais antigo; não há ordenação configurável |
| Erros | RFC 9457 (Problem Details): `{"type", "title", "status", "detail"}`; erro de validação (422) traz também a lista `errors` |
| Idioma | Mensagens (`title`, `detail`) em português ou inglês, conforme o header `Accept-Language` (nas telas, o idioma da pessoa). As mensagens são escritas em português e traduzidas pelo catálogo em `core/i18n.py` |
| Idempotência | Header `Idempotency-Key` (até 255 caracteres) em `POST` com token de API: a primeira resposta de sucesso volta igual, com `Idempotent-Replayed: true`, sem executar de novo; mesma chave com outro corpo, 422; a primeira ainda em andamento, 409 (parada há mais de 5 min, a nova assume); erro não fica guardado. Vale por pelo menos 24 h, por token. Opcional, mas recomendado para integrações e agentes de IA, que repetem chamadas |
| Concorrência | `ETag` / `If-Match` em `PATCH` para evitar sobrescrever alteração de outro usuário. O `GET /tickets/{id}` e o `PATCH` devolvem o header `ETag` (também no campo `etag`), que só muda quando um campo que o `PATCH` altera muda. Com `If-Match` desatualizado, **412**; sem `If-Match`, o `PATCH` grava como antes |
| Versionamento | Mudanças incompatíveis só em uma nova versão (`/api/v2`); campos novos são aditivos |
| Rate limit | Por token de API (o cabeçalho `Authorization`), na API e no MCP, pelo nginx: 10 requisições por segundo, com folga para rajadas de até 20; acima disso, `429` com `Retry-After: 1`. As telas (sem o cabeçalho) não têm limite. Os headers `RateLimit-*` ficam para depois |
| CORS | Desnecessário: as telas são servidas na mesma origem da API |

## Autenticação

| Cliente | Mecanismo |
|---------|-----------|
| Interface web (telas do servidor) | Sessão via cookie `HttpOnly` + `Secure` + `SameSite=Lax` + token CSRF num campo escondido do formulário ou no header (HTMX e envio de anexos). Nenhum token fica no `localStorage` |
| Integrações e agentes de IA | `Authorization: Bearer <token>`, um token de API com as permissões escolhidas por área (abaixo) |

### Tokens de API

Desde 2026-10-23. Um token sempre age **em nome de um usuário**: passa pelas mesmas permissões e pela mesma visibilidade dele, e o que faz aparece no histórico e na auditoria como dele, com `via: "api"` no histórico. Só quem tem `admin.users` cria tokens (no próprio nome), vê os tokens ativos de todos, muda as permissões deles e revoga qualquer um, na tela **Administração → Tokens de API** (`/admin/tokens`) ou por `POST`/`GET /admin/api-tokens`, `PATCH /admin/api-tokens/{id}` (`{"permissions": [...]}`; o valor continua o mesmo) e `DELETE /admin/api-tokens/{id}` (só com a sessão da interface: nenhum token entra nessas rotas; o valor vem uma vez, no campo `token` da criação; validade de 1 a 365 dias, padrão 90, ou `null` para sem validade). Quem administra o servidor também pode usar o comando `chamados token` ([ARCHITECTURE 3.10](../ARCHITECTURE.md#310-comando-chamados-clipy)).

```
Authorization: Bearer tf_...
```

Cada token tem a lista `permissions`, com códigos `área.ação` (na criação, ao menos um):

| Área | Ações | Rotas |
|------|-------|-------|
| `tickets` | `view`, `create`, `edit`, `delete` | Ver: listar e ler chamados, tarefas, histórico e anexos. Criar: `POST /tickets`. Editar: alterar, status, responsáveis, transferir, registrar e alterar tarefas. Excluir: remover tarefas. Enviar anexo pede criar ou editar |
| `clients` | `view`, `create`, `edit` | O cadastro de clientes (`/clients`) |
| `users` | `view`, `create`, `edit`, `delete` | `/users` |
| `teams` | `create`, `edit`, `delete` | Criar e alterar grupos; incluir (editar) e tirar (excluir) membros |
| `catalog` | `create`, `edit`, `delete` | Categorias e status (inclusive ordenar) |
| `reports` | `view` | `/reports` (com o PDF e o CSV) |
| `settings` | `view`, `edit` | `/admin/settings/*` |
| `audit` | `view` | `/admin/audit-log` |

- **Sempre limitado ao dono:** a permissão do token só abre a porta; a rota ainda exige a do dono (um token com `users.view` de quem não tem `admin.users` recebe 403), as regras do chamado e a visibilidade.
- **Listas de apoio:** qualquer token lê `GET /me`, `/teams` (sem os e-mails dos membros), `/categories`, `/statuses`, `/resolution-codes`, `/clients/options` e `/work-hours`, que servem para preencher um chamado.
- **Nunca com token:** as rotas `/admin/api-tokens` e `PATCH /me`. Sem a permissão, a resposta é 403 "Este token de API não tem permissão para esta ação."
- **Só pela interface:** sair e trocar a senha (403 com token). Enquanto a pessoa tem a senha provisória, o token dela recebe 403 em tudo, até ela trocá-la na tela.
- **Leitura não conta como visita:** abrir um chamado com um token (`GET /tickets/{id}`) não apaga o aviso de novidade da pessoa (`has_news`), que continua até ela abrir o chamado na tela.
- Token inválido, revogado, vencido ou de usuário inativo/excluído: 401. Desativar ou excluir a pessoa revoga os tokens dela: reativar a conta não os traz de volta. Requisições com token não usam cookie nem CSRF.

**Depois:** contas de serviço (`actor_kind = api_client` ou `ai`).

## Endpoints

### Chamados

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/tickets` | Listar e filtrar: fila (`view`: `mine`, `waiting`, `all`), `team` (id do grupo), `assignee` (`me` ou o id), `status` (comportamento: `open`, `waiting`, `delivered`, `closed`, `canceled`) e a busca textual `q` (título, descrição, tarefas, número, cliente e contato). Cada item traz `has_news` e `time_spent_minutes` |
| `GET` | `/tickets/counts` | Quantos chamados há em cada fila (os contadores das abas); em `all`, os em andamento |
| `POST` | `/tickets` | Registrar: `title`, `client_id` (cliente ativo) e `assignee` (`"me"` ou um membro do grupo) são obrigatórios; também `team_id`, `description` (Markdown), `beneficiary_name` (o contato), `category_id`, `type`, `status_id`, `started_at`, `co_assignee_ids` e `attachment_ids`. Sem `team_id`, vale o grupo padrão da categoria. Responde 201 com `Location` |
| `GET` | `/tickets/{id}` | Detalhe, com `allowed_actions`, `attachments`, o tempo gasto (total e por pessoa) e `etag` |
| `PATCH` | `/tickets/{id}` | Alterar campos: `title`, `description`, `category_id` (nulo tira), `type`, `client_id`, `beneficiary_name`, `started_at`, `status_id` (qualquer status, sem as exigências do fluxo) e `finished_at` (a data da conclusão ou do cancelamento, nunca no futuro). Aceita `If-Match` |
| `POST` | `/tickets/bulk/status` | O mesmo status em vários chamados: `{"numbers": [...], "status_id"}` (até 200; supervisor do grupo ou admin). Responde `{"updated": [...], "failed": [{"number", "detail"}]}` |
| `POST` | `/tickets/{id}/transitions` | Mudar status pelo fluxo: `{"action": "close", "comment": "...", "resolution_code_id": ...}`. Ações: `wait`, `resume`, `close`, `reopen`, `cancel` ([10.5](10-chamados.md#105-status-e-fluxo)); o comentário vira uma tarefa do chamado |
| `POST` | `/tickets/{id}/assign` | Assumir (`{"assignee": "me"}`) ou atribuir (id de um membro do grupo); o chamado nunca fica sem responsável |
| `PUT` | `/tickets/{id}/assignees` | Vários responsáveis (ou o grupo todo): `{"assignee_ids": [...]}`, a lista inteira; quem entra é membro ativo do grupo (quem já estava e saiu do grupo pode ficar ou sair); o principal continua se estiver nela, senão o primeiro assume |
| `POST` | `/tickets/{id}/transfer` | Transferir: `{"team_id", "assignee_id", "reason"}`; o novo responsável é um membro ativo do grupo de destino, e o motivo vira uma tarefa |
| `GET` | `/tickets/{id}/comments` | Listar as tarefas (os andamentos) |
| `POST` | `/tickets/{id}/comments` | Registrar uma tarefa: `{"body", "time_spent_minutes", "done_at", "attachment_ids": [...]}`. Só `body` é obrigatório; `time_spent_minutes` vai de 1 a 60000; sem `done_at`, a tarefa é de agora |
| `PATCH` | `/tickets/{id}/comments/{cid}` | Editar a própria tarefa, a qualquer momento (o corpo inteiro, como no `POST`; sem `done_at`, a data continua). A versão anterior fica no histórico |
| `DELETE` | `/tickets/{id}/comments/{cid}` | Remover a própria tarefa: sai da tela e do tempo gasto; o texto fica no histórico. Responde 204 |
| `GET` | `/tickets/{id}/events` | Histórico: cada mudança, com quem fez, antes e depois |

O detalhe do chamado inclui `allowed_actions` (ex.: `["comment", "edit", "set_status", "assign_self", "transfer", "close"]`), calculado pelo backend, para a interface decidir quais botões mostrar.

Um chamado que o usuário não pode ver responde `403` ("Você não tem acesso a este chamado"); um número inexistente, `404`. Sem `team_id`, `POST /tickets` usa o grupo padrão da categoria (roteamento), que precisa ser um dos grupos do usuário.

### Anexos

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/uploads` | Envia um arquivo (1ª etapa, multipart, campo `file`, até 25 MB). Ver [11.4](11-anexos-e-arquivos.md#114-fluxo-de-envio-em-duas-etapas). O vínculo vem depois, em `attachment_ids` no registro, na tarefa (e na edição dela), na mudança de status pelo fluxo e no `PATCH` do chamado (imagens da descrição); o que não for vinculado em 24 h é apagado |
| `GET` | `/attachments/{id}` | Baixa (verifica permissão). O detalhe do chamado lista os anexos em `attachments` |

### Relatórios

Horas trabalhadas no período, com o escopo da pessoa (o que ela vê). Filtros comuns: `start` e `end` (datas, obrigatórias, `end` incluído), `team`, `person`, `client` (ids; repita para vários), `no_client` (inclui os chamados sem cliente) e `status` (ids).

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/reports/options` | As opções dos filtros (grupos, pessoas, clientes, status) |
| `GET` | `/reports` | Os números do período: por pessoa, por cliente e por dia, e as horas fora do expediente |
| `GET` | `/reports/pdf` | O mesmo em PDF (`locale` opcional: o idioma do arquivo) |
| `GET` | `/reports/csv` | Uma tabela em CSV: `table` = `people`, `clients`, `overtime` ou `tasks` (todas as tarefas) |

No `GET /reports`, cada linha de `clients` traz também o plano do contrato do cliente: `in_plan_minutes` e `excess_minutes` (`minutes` é a soma dos dois; sem plano mensal ou anual, tudo é excedente). O CSV `clients` tem as mesmas colunas, no fim. As horas descontadas da aba Clientes são só da tela. Todo PDF e CSV vai para a auditoria (`report.exported`).

### Configurações

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/branding` | **Pública** (a tela de login usa): idioma padrão, as 3 cores (`null` = padrão) e os endereços do logotipo e do logotipo dos relatórios |
| `GET` | `/branding/logo` | Imagem do logotipo (endereço versionado, guardado em cache pelo navegador) |
| `GET` | `/branding/report-logo` | Imagem do logotipo dos relatórios (PDFs), como a do logotipo |
| `GET` | `/work-hours` | O expediente da instalação e os feriados (qualquer pessoa logada) |
| `PATCH` | `/admin/settings` | `{"default_locale": "pt-BR" \| "en", "colors": {"brand", "neutral", "background"} \| null}` (`admin.settings`) |
| `PUT` / `DELETE` | `/admin/settings/logo` | Envia (`{"data_url": "data:image/png;base64,..."}`, PNG, JPEG ou WebP até 256 KB) ou remove o logotipo |
| `PUT` / `DELETE` | `/admin/settings/report-logo` | O mesmo, para o logotipo dos relatórios, separado do logotipo do aplicativo |
| `GET` / `PUT` | `/admin/settings/report-filters` | Os filtros que a tela de Relatórios mostra: `period`, `team`, `person`, `status` e `compare`, todos `true` por padrão. Desligado, o campo some da tela e vale o padrão da aba; a API dos relatórios não muda (`admin.settings`) |
| `GET` / `PUT` | `/admin/settings/ticket-list` | Quantos chamados a lista da tela mostra por página: `page_size` 25 (padrão), 50, 75, 100 ou nulo (todos) (`admin.settings`) |
| `PUT` | `/admin/settings/work-hours` | O expediente da instalação e os feriados (`admin.settings`) |
| `GET` / `PUT` | `/admin/settings/company` | Os dados da empresa que usa o sistema (`null` enquanto não cadastrados): `name` (razão social) e `document` (CNPJ) obrigatórios; `trade_name`, `state_registration`, `municipal_registration`, `phone`, `email`, `website`, `postal_code`, `street`, `number`, `complement`, `district`, `city` e `state` opcionais. O `PUT` substitui tudo e devolve os valores normalizados (só dígitos no CNPJ, telefone e CEP) (`admin.settings`) |
| `PATCH` | `/me` | Preferências da pessoa: `{"locale": "en" \| "pt-BR" \| null}` (nulo segue o padrão do sistema) |

### Demais recursos

`/auth/*` e `/me` (ver [Login e autenticação](09-login-e-autenticacao.md#99-endpoints)), `/users`, `/teams`, `/categories`, `/statuses`, `/resolution-codes`, `/clients` (o cadastro, só para o grupo que gerencia clientes; `/clients/options` para qualquer pessoa logada), `/admin/api-tokens`, `/admin/audit-log` e `/api/health` (fora de `/v1`). A lista completa, com os schemas, está no OpenAPI.

### Futuro

Ainda não existem: vincular e mesclar chamados (`/tickets/{id}/links`, `/tickets/{id}/merge`), aprovações (`/tickets/{id}/approvals`, `/approvals`), ocultar tarefa ou anexo com motivo (`.../hide`), `/notifications`, a base de conhecimento (`/kb/articles`), `/saved-views`, `/admin/idp-mappings`, `/admin/api-clients`, `/admin/webhooks`, `/admin/ai` e as rotas de IA abaixo.

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/tickets/{id}/ai/summary` | Gerar ou obter resumo |
| `POST` | `/tickets/{id}/ai/suggest-reply` | Sugestão de resposta para o agente |
| `GET` | `/tickets/{id}/ai/suggestions` | Sugestões pendentes (classificação, duplicados) |
| `POST` | `/ai/suggestions/{run_id}/feedback` | `{"feedback": "accepted" \| "edited" \| "rejected"}` |
| `GET` | `/tickets/{id}/similar` | Chamados semelhantes (busca vetorial) |

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

Até lá, uma integração acompanha as mudanças consultando `GET /tickets` (os itens trazem `updated_at`) e `GET /tickets/{id}/events`.

## Exemplo: abrir um chamado

Os ids de grupo e de cliente vêm de `GET /teams` e `GET /clients/options?q=...`.

```http
POST /api/v1/tickets
Authorization: Bearer tf_...
Idempotency-Key: 6f1c2a9e-3b7d-4e0a-9d51-2c8f4b7a1e30
Content-Type: application/json

{
  "title": "Impressora do 3º andar não imprime",
  "description": "Financeiro avisou por telefone: aparece 'offline'.",
  "team_id": "5a0c...",
  "client_id": "c3d9...",
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
  "status": { "id": 1, "name": "Pendente", "kind": "open" },
  "team": { "id": "5a0c...", "name": "TI - Suporte" },
  "client": { "id": "c3d9...", "name": "Cliente Exemplo" },
  "...": "..."
}
```

Repetir a mesma requisição com a mesma `Idempotency-Key` devolve o mesmo chamado (com `Idempotent-Replayed: true`), sem registrar outro.
