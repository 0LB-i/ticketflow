# 4. Modelo de dados

Esboço completo e comentado: [`esboco-schema.sql`](esboco-schema.sql). Ele é o ponto de partida da primeira migração Alembic e ainda vai mudar.

## Diagrama de entidades (simplificado)

```mermaid
erDiagram
    users ||--o{ team_members : participa
    teams ||--o{ team_members : tem
    teams ||--o{ categories : "atende (padrão)"
    categories ||--o{ categories : subcategoria
    users ||--o{ tickets : solicita
    users ||--o{ tickets : "atende (assignee)"
    teams ||--o{ tickets : fila
    categories ||--o{ tickets : classifica
    ticket_statuses ||--o{ tickets : status
    tickets ||--o{ ticket_comments : tem
    tickets ||--o{ ticket_attachments : tem
    tickets ||--o{ ticket_events : historico
    tickets ||--o{ ticket_watchers : observadores
    tickets ||--o{ ticket_links : vinculos
    tickets ||--o| ticket_sla : prazos
    sla_policies ||--o{ ticket_sla : aplica
    business_calendars ||--o{ sla_policies : usa
    kb_articles ||--o{ embeddings : indexado
    tickets ||--o{ embeddings : indexado
    tickets ||--o{ ai_runs : "IA executada"
    api_clients ||--o{ api_tokens : possui
    webhook_subscriptions ||--o{ webhook_deliveries : entrega
```

## Decisões de modelagem

| Tema | Decisão | Motivo |
|------|---------|--------|
| Chave primária | `bigint GENERATED ALWAYS AS IDENTITY` internamente + `public_id uuid` exposto na API | Joins e índices compactos; não expõe IDs sequenciais adivinháveis. `gen_random_uuid()` é nativo desde o PG 13 (o `uuidv7()` nativo só existe a partir do PG 18) |
| Número do chamado | Coluna `number` alimentada pela sequence `ticket_number_seq`, exibida como `#000123` | Legível para humanos |
| Status | Tabela `ticket_statuses` com um `kind` fixo (`new`, `open`, `pending`, `resolved`, `closed`, `canceled`) | Nomes de status configuráveis, enquanto as regras (SLA pausa em `pending`) dependem do `kind` |
| Prioridade | `smallint` 1–4 com `CHECK` | Simples e ordenável |
| Datas | Sempre `timestamptz` | Evita problemas de fuso horário |
| Histórico | `ticket_events` só aceita inserção (append-only), com `payload jsonb` (antes/depois) | Auditoria completa, base para a linha do tempo |
| Campos personalizados | `custom_fields jsonb` no chamado + definição JSON Schema na categoria | Flexível sem migração a cada novo campo |
| Busca textual | Coluna gerada `search_vector` com configuração `pt_br` (português + unaccent) e índice GIN | Nativo e mantido automaticamente |
| Busca semântica | Tabela `embeddings` com `vector` (pgvector) e índice HNSW | Uma tabela para chamados, comentários e artigos |
| Exclusão | Exclusão lógica (`deleted_at`) para chamados; anonimização para atender à LGPD | Preserva auditoria e permite o direito ao esquecimento |
| Multi-empresa | **Em aberto**. O esboço é *single-tenant* (uma instalação por empresa) | Ver [questões em aberto](questoes-em-aberto.md) |

## Compatibilidade PostgreSQL 16 × 17

O schema usa apenas recursos disponíveis nas **duas** versões. Recursos exclusivos do 17, como `JSON_TABLE`, as funções SQL/JSON (`JSON_QUERY`, `JSON_VALUE`, `JSON_EXISTS`) e o `MERGE ... RETURNING`, **não** devem ser usados no código da aplicação enquanto o 16 for suportado. O CI roda os testes nas duas versões.

Extensões necessárias:

- `pgvector` (≥ 0.7): busca semântica
- `unaccent`: busca sem acentos (contrib, já vem com o PostgreSQL)
- `pg_trgm`: busca por similaridade em títulos e autocompletar (contrib)
- `citext`: e-mails sem distinção de maiúsculas e minúsculas (contrib)

## Volumes estimados (para dimensionar índices)

| Tabela | Volume em 3 anos (empresa média) |
|--------|----------------------------------|
| `tickets` | ~500 mil |
| `ticket_comments` | ~3 milhões |
| `ticket_events` | ~10 milhões, candidata a particionamento por mês |
| `embeddings` | ~1 milhão |
| `ai_runs` | ~2 milhões, candidata a particionamento e expurgo |
