#!/usr/bin/env bash
# Verificação local, no lugar do CI (docs/12 §12.3).
#   scripts/check.sh --rapido    lint e formatação dos arquivos no stage (hook de pre-commit)
#   scripts/check.sh             tudo do rápido + tipos e os testes que a mudança afeta (só web/:
#                                tests/unidade e tests/telas; fora de web/ e docs: todos)
#   scripts/check.sh --completo  tudo + todos os testes no PostgreSQL 17 e 16 e auditoria de
#                                dependências
set -euo pipefail
cd "$(dirname "$0")/.."

modo="${1:-padrao}"
case "$modo" in --rapido | padrao | --completo) ;; *) echo "uso: $0 [--rapido|--completo]" >&2; exit 2 ;; esac

PG17_URL="${TEST_DATABASE_URL:-postgresql+psycopg://chamados:chamados@localhost:5432/chamados_test}"
PG16_URL="${TEST_DATABASE_URL_PG16:-postgresql+psycopg://chamados:chamados@localhost:5433/chamados_test}"

etapa() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

segredos() {
  # Padrões de chaves e tokens que nunca devem entrar no repositório.
  local padrao='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{32,}'
  if git diff --cached -U0 | grep '^+' | grep -E -q -- "$padrao"; then
    echo "Possível segredo nos arquivos do commit. Remova antes de commitar." >&2
    exit 1
  fi
}

# As pastas de backend/tests que a mudança desde o último commit (inclusive arquivos novos) pode
# afetar, uma por linha. Sem mudança, ou com alguma fora das regras abaixo, "todas".
pastas_afetadas() {
  local -a arquivos
  local -A pastas=()
  local f pasta
  mapfile -t arquivos < <({ git diff --name-only HEAD; git ls-files --others --exclude-standard; } | sort -u)
  if ((${#arquivos[@]} == 0)); then
    echo todas
    return
  fi
  for f in "${arquivos[@]}"; do
    case "$f" in
      # O benchmark (backend/bench) não entra nos testes: roda à parte, com python -m bench.
      docs/* | deploy/* | scripts/* | *.md | .gitignore | backend/bench/*) ;;
      # Só a API usa web/ (as páginas de erro fora de /api), e esses testes estão em telas.
      backend/src/chamados/web/*) pastas[tests/unidade]=1 pastas[tests/telas]=1 ;;
      backend/tests/*/*)
        pasta="tests/$(cut -d/ -f3 <<<"$f")"
        [[ -d "backend/$pasta" ]] && pastas[$pasta]=1
        ;;
      *)
        echo todas
        return
        ;;
    esac
  done
  printf '%s\n' "${!pastas[@]}" | sort
}

banco_no_ar() {
  local porta="$1"
  if ! pg_isready -q -h localhost -p "$porta"; then
    echo "PostgreSQL não responde em localhost:$porta (veja o README, \"Como rodar\")." >&2
    exit 1
  fi
}

if [[ "$modo" == --rapido ]]; then
  segredos
  mapfile -t py < <(git diff --cached --name-only --diff-filter=ACMR -- 'backend/*.py' | sed 's|^backend/||')
  if ((${#py[@]})); then
    etapa "backend: ruff (${#py[@]} arquivos)"
    (cd backend && uv run --frozen ruff check "${py[@]}" && uv run --frozen ruff format --check "${py[@]}")
  fi
  exit 0
fi

etapa "backend: ruff, mypy"
(cd backend && uv sync -q --frozen && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests bench)

etapa "backend: testes no PostgreSQL 17"
banco_no_ar 5432
pastas=(todas)
[[ "$modo" == --completo ]] || mapfile -t pastas < <(pastas_afetadas)
if [[ "${pastas[0]:-}" == todas ]]; then
  (cd backend && TEST_DATABASE_URL="$PG17_URL" uv run pytest -q --cov)
elif ((${#pastas[@]})); then
  # A cobertura mínima só vale para a suíte inteira.
  echo "Só o que a mudança afeta: ${pastas[*]} (a suíte inteira: --completo)"
  (cd backend && TEST_DATABASE_URL="$PG17_URL" uv run pytest -q "${pastas[@]}")
else
  echo "Nenhum teste afetado pela mudança (a suíte inteira: --completo)."
fi

if [[ "$modo" == --completo ]]; then
  etapa "backend: testes no PostgreSQL 16"
  banco_no_ar 5433
  (cd backend && TEST_DATABASE_URL="$PG16_URL" uv run pytest -q)

  etapa "auditoria de dependências"
  requisitos="$(mktemp)"
  trap 'rm -f "$requisitos"' EXIT
  (cd backend && uv export -q --frozen --no-emit-project -o "$requisitos" && uvx -q pip-audit --require-hashes --disable-pip -r "$requisitos")

  # Playwright entra com os testes ponta a ponta (F1-S5-04).
fi

etapa "tudo certo ($modo)"
