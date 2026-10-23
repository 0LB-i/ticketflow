Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 0. Git — Regra de ouro

**Todos os commits vão direto para `main`.** Não criar branches de feature/fix separadas.
Se já houver commits em branches separadas, fazer cherry-pick para `main` antes de prosseguir.

## 0.1 Serviço web — Regra de ouro

**Não reiniciar o `ticketflow.service` nem o `ticketflow-css.service`, e não subir instâncias extras do uvicorn em portas alternativas para validar mudanças.** Quem confere o resultado no navegador é o usuário. Uma instância de teste numa porta alternativa pode colidir com recursos compartilhados do serviço real (ex: arquivo de log com rotação do loguru) e derrubar o ambiente.

Na máquina de desenvolvimento os serviços rodam em modo dev (`scripts/instalar-servico-dev.sh`): o uvicorn (`--reload`) se reinicia sozinho a cada mudança e o `ticketflow-css.service` gera de novo o CSS a cada mudança nos templates. **Não há build**: basta o usuário recarregar a página para ver uma mudança. Migração nova continua manual: aplicar no banco de dev (`cd backend && set -a && . /etc/ticketflow/env && set +a && uv run chamados db upgrade`).

## 0.2 Estrutura do código

**Antes de criar módulo, tela, tabela ou permissão, leia o [ARCHITECTURE.md](ARCHITECTURE.md)** (mapa do código, regras da arquitetura e receitas). Se a mudança alterar a estrutura, atualize-o no mesmo commit.

## 0.3 Verificação sem desperdício

Durante a tarefa, rodar só o que a mudança afeta: o arquivo ou a pasta da área (`uv run pytest tests/telas/test_web_board.py`, `uv run pytest tests/telas`). Os testes ficam por área em `backend/tests/`: `unidade`, `api`, `telas`, `banco` e `worker` (ARCHITECTURE.md §7). O `scripts/check.sh` roda **uma vez**, antes do commit, e escolhe sozinho as pastas pelo que mudou (só `web/` → `unidade` e `telas`); a suíte inteira é o `--completo`.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.