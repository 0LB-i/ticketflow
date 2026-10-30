#!/usr/bin/env bash
# Atualiza a instalação para a versão mais nova da main (docs/18 §18.4): baixa o código, instala
# as dependências, gera o CSS das telas e aplica as migrações.
#
#   sudo /opt/ticketflow/update.sh            # para se houver mudança local ou o histórico divergir
#   sudo /opt/ticketflow/update.sh --force    # descarta as mudanças locais e fica igual à main
#
# Com --force, também volta à main quem estava numa versão anterior (git checkout <tag>).
# Roda como o dono do código (o usuário ticketflow, na produção); chamado pelo root, troca para ele.
# Não reinicia os serviços: quem reinicia é o administrador (ADR 0010).
set -euo pipefail
cd "$(dirname "$0")"

FORCAR=false
case "${1:-}" in
  "") ;;
  --force) FORCAR=true ;;
  *) echo "uso: $0 [--force]" >&2; exit 2 ;;
esac

DONO="$(stat -c %U .)"
if [[ "$(id -un)" != "$DONO" ]]; then
  [[ $EUID -eq 0 ]] || { echo "Rode como root (sudo) ou como $DONO." >&2; exit 1; }
  exec sudo -u "$DONO" -H "$PWD/update.sh" "$@"
fi

ENV_FILE="${ENV_FILE:-/etc/ticketflow/env}"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

etapa() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

etapa "código"
ANTES="$(git describe --tags --always)"
git fetch -q origin main
if $FORCAR; then
  git checkout -q -f -B main origin/main
elif [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  git status --short --untracked-files=no >&2
  echo "Há mudanças locais no código. Para descartá-las e atualizar: $0 --force" >&2
  exit 1
elif ! git -c advice.diverging=false merge -q --ff-only origin/main 2>/dev/null; then
  echo "O código local divergiu da main. Para ficar igual à main: $0 --force" >&2
  exit 1
fi
echo "$ANTES -> $(git describe --tags --always)"

etapa "dependências"
(cd backend && uv sync -q --frozen --no-dev)

etapa "CSS das telas"
scripts/css.sh

etapa "migrações"
(cd backend && .venv/bin/chamados db upgrade)

cat <<FIM

Pronto: versão $(git describe --tags --always) preparada.
Para colocar no ar, reinicie os serviços:
  sudo systemctl restart ticketflow    # o worker reinicia junto
FIM
