# 0012. Conexões do aplicativo com o JIT do PostgreSQL desligado

- **Status:** Aceita
- **Data:** 2026-10-24
- **Medição:** benchmark do [ARCHITECTURE 7.1](../../ARCHITECTURE.md#71-benchmark-backendbench) (`cd backend && uv run python -m bench`)

## Contexto

O RNF-01 ([docs/02](../02-requisitos.md#requisitos-não-funcionais)) pede p95 < 300 ms nas leituras com 50 mil chamados. Com essa massa, o benchmark mostrou listas, buscas, contadores e o quadro passando de 1 s, e o `EXPLAIN ANALYZE` mostrou o motivo: a consulta não era lenta, o JIT era.

O JIT do PostgreSQL compila a consulta para código de máquina quando o **custo estimado** passa de `jit_above_cost` (100 mil, o padrão). O filtro de visibilidade (`tickets/visibility.py`) junta várias regras com `OR EXISTS (...)`. O planejador não consegue estimar quantas linhas passam por ele e infla o custo. A lista "Meus" do agente, por exemplo, ficou com custo estimado de ~760 mil: a execução levou **23 ms**, e a compilação do JIT, **736 ms**. Na busca, foram 112 ms de execução para ~1 s de JIT.

O JIT só compensa em consultas que varrem milhões de linhas por vários segundos (relatórios analíticos, data warehouse). As do TicketFlow rodam em dezenas de milissegundos. Medimos também os relatórios mais pesados, com e sem JIT, e o tempo deles não mudou: está no Python, não no banco.

## Decisão

A engine do aplicativo (`db/engine.py`) abre as conexões com `options=-c jit=off`. Vale para o app, o worker e o comando `chamados`, que usam essa engine.

A configuração do servidor PostgreSQL **não muda**: outros programas no mesmo banco continuam com o padrão, e quem administra o servidor não tem nada a fazer. Na produção, a mudança passa a valer com o `deploy.sh` e o restart do serviço, como qualquer mudança em Python.

## Alternativas consideradas

- **Subir o `jit_above_cost`:** resolve hoje, mas o custo estimado do filtro de visibilidade cresce com o número de chamados e cruzaria o novo limite mais adiante, com o mesmo sintoma.
- **Reescrever o filtro de visibilidade** para o planejador estimar melhor: mais trabalho e mais risco numa regra crítica ([docs/08](../08-organizacao-e-permissoes.md) §8.4), para um ganho que desligar o JIT já entrega.
- **Desligar o JIT no `postgresql.conf`:** o mesmo efeito, mas fica fora do código, depende de quem administra o servidor e afeta outros bancos da mesma instância.

## Consequências

- Listas, buscas, contadores e telas de chamados caíram de ~1 s para 30 a 150 ms com 50 mil chamados. Com o índice da ordem da lista (migração 0037), 28 dos 33 cenários do benchmark ficaram dentro da meta.
- Uma consulta que um dia precise do JIT (um relatório que varra milhões de linhas) pode ligá-lo só para ela, com `SET LOCAL jit = on` na transação, e o benchmark mostra se compensa.
- Para reverter, basta tirar o `connect_args` de `db/engine.py`.
