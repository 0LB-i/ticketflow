# 0003. PostgreSQL 17 com suporte a 16, e o banco como fila e motor de busca

- **Status:** Proposta
- **Data:** 2026-10-09

> **Nota (2026-10-09):** o `pgvector` só será necessário quando a IA entrar (depois da v1.0). A v1.0 usa apenas extensões que vêm com o PostgreSQL.

> **Nota (2026-10-21):** a fila de tarefas e o outbox são próprios (F1-S4-03, [ARCHITECTURE 3.12](../../ARCHITECTURE.md#312-worker-outbox-e-fila-de-tarefas-modulesjobs)). O Procrastinate foi descartado: o schema dele (tabelas, funções e triggers) ficaria fora do Alembic, ele usa um pool de conexões próprio e não tem outbox; como o worker é quem cria as tarefas a partir do outbox, a maior vantagem dele (gravar a tarefa na transação da mudança) não seria usada. A tabela `jobs` não tem `queue` nem o status `running` (a linha fica travada enquanto a tarefa roda) e ganhou `dedup_key`, usada pelas rotinas diárias no lugar do advisory lock.

## Contexto

O requisito é PostgreSQL 16 ou 17. Queremos operação simples em ambientes corporativos, onde cada componente extra (Redis, RabbitMQ, Elasticsearch, banco vetorial) é mais um item para aprovar, monitorar e manter.

## Decisão

- **Versão alvo: PostgreSQL 17**, com suporte oficial ao **16**. O CI roda nas duas versões. Recursos exclusivos do 17 (ex.: `JSON_TABLE`, funções SQL/JSON, `MERGE ... RETURNING`) não são usados enquanto o 16 for suportado.
- O PostgreSQL também cumpre os papéis de:
  - **fila de tarefas:** tabela `jobs` + `SELECT ... FOR UPDATE SKIP LOCKED` (avaliar a biblioteca Procrastinate antes de escrever a nossa);
  - **outbox de eventos:** tabela `outbox`, na mesma transação da mudança;
  - **busca textual:** `tsvector` com configuração `pt_br` (português + `unaccent`), índices GIN, e `pg_trgm` para similaridade;
  - **busca vetorial:** extensão `pgvector` com índice HNSW;
  - **locks distribuídos:** advisory locks para tarefas agendadas.
- Imagem de desenvolvimento: `pgvector/pgvector:pg17`.

## Alternativas consideradas

- **Redis + Celery/RQ para a fila:** mais throughput, porém mais um serviço, e perde a atomicidade com os dados. O volume de um help desk interno não justifica.
- **Elasticsearch/OpenSearch:** busca mais rica, porém exige operação pesada e sincronização de índices.
- **Banco vetorial dedicado (Qdrant, Weaviate):** desnecessário na escala esperada (cerca de 1 milhão de vetores).

## Consequências

- Precisamos de pgvector disponível no ambiente de produção. Verificar se o PostgreSQL gerenciado do cliente (RDS, Azure, Cloud SQL) oferece a extensão; os principais oferecem.
- Se a fila ou a busca virarem gargalo, reavaliar com métricas e substituir atrás das mesmas interfaces.
