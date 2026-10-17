#!/usr/bin/env bash
# CSS das telas do servidor (ADR 0011): Tailwind standalone pelo pytailwindcss, sem Node.
#   scripts/css.sh           gera backend/src/chamados/web/static/css/app.css, minificado
#   scripts/css.sh --watch   gera de novo a cada mudança nos templates (modo de desenvolvimento)
# O app.css não vai para o git: o deploy e o serviço de desenvolvimento o geram.
set -euo pipefail
cd "$(dirname "$0")/../backend"

# Mesma versão em todas as máquinas; na primeira vez o binário é baixado do GitHub.
export TAILWINDCSS_VERSION=v4.3.3
css=src/chamados/web/static/css

case "${1:-}" in
  "") exec .venv/bin/tailwindcss -i "$css/input.css" -o "$css/app.css" --minify ;;
  --watch) exec .venv/bin/tailwindcss -i "$css/input.css" -o "$css/app.css" --watch=always ;;
  *) echo "uso: $0 [--watch]" >&2; exit 2 ;;
esac
