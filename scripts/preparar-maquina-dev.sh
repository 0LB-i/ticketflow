#!/usr/bin/env bash
# Prepara um Ubuntu 24.04 novo para desenvolver o TicketFlow, com o mesmo ambiente da máquina
# original: uv, PostgreSQL 17 (porta 5432) e 16 (porta 5433, para
# a verificação completa), o usuário e os bancos de desenvolvimento, o código em /opt/ticketflow
# e as dependências. Roda como root (sudo); o código fica com quem chamou o sudo.
#
#   curl -fsSLO https://raw.githubusercontent.com/0LB-i/ticketflow/main/scripts/preparar-maquina-dev.sh
#   sudo bash preparar-maquina-dev.sh              # ambiente de desenvolvimento
#   sudo bash preparar-maquina-dev.sh --servico    # e também o ticketflow.service (porta 8000)
#
# Variáveis opcionais: GIT_NOME e GIT_EMAIL (autor dos commits neste repositório) e DESTINO
# (padrão /opt/ticketflow; o serviço só funciona nesse caminho, que é o das units).
# Pode rodar de novo: o que já existe é mantido (pacotes instalados não são atualizados).
set -euo pipefail

REPO_HTTPS=https://github.com/0LB-i/ticketflow.git
REPO_SSH=git@github-ticketflow:0LB-i/ticketflow.git
DESTINO="${DESTINO:-/opt/ticketflow}"
SERVICO=0
for arg in "$@"; do
  case "$arg" in
    --servico) SERVICO=1 ;;
    *) echo "uso: $0 [--servico]" >&2; exit 2 ;;
  esac
done

etapa() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "Rode como root (sudo)." >&2; exit 1; }
# shellcheck disable=SC1091
. /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] ||
  echo "Aviso: feito para Ubuntu 24.04; esta máquina é $PRETTY_NAME." >&2
if [[ $SERVICO == 1 && "$DESTINO" != /opt/ticketflow ]]; then
  echo "--servico exige o código em /opt/ticketflow (caminho das units do systemd)." >&2
  exit 2
fi

# Quem vai desenvolver: quem chamou o sudo (ou o próprio root).
DEV="${SUDO_USER:-root}"
GRUPO_DEV="$(id -gn "$DEV")"
export DEBIAN_FRONTEND=noninteractive
como_dev() {
  if [[ "$DEV" == root ]]; then
    bash -c "$1"
  else
    sudo -u "$DEV" -H bash -c "$1"
  fi
}

etapa "pacotes básicos"
apt-get update -q
apt-get install -y -q --no-upgrade git curl ca-certificates gnupg rsync build-essential

etapa "PostgreSQL 17 e 16 (repositório oficial do PostgreSQL)"
if [[ ! -f /etc/apt/sources.list.d/pgdg.sources && ! -f /etc/apt/sources.list.d/pgdg.list ]]; then
  apt-get install -y -q --no-upgrade postgresql-common
  /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
fi
# O 17 primeiro, para ficar com a porta 5432; o 16, instalado depois, fica com a 5433.
apt-get install -y -q --no-upgrade postgresql-17
apt-get install -y -q --no-upgrade postgresql-16
porta() { pg_lsclusters -h | awk -v v="$1" '$1 == v && $2 == "main" { print $3 }'; }
if [[ "$(porta 17)" != 5432 || "$(porta 16)" != 5433 ]]; then
  echo "Esperava o PostgreSQL 17 na porta 5432 e o 16 na 5433. Está assim:" >&2
  pg_lsclusters >&2
  exit 1
fi

etapa "usuário e bancos de desenvolvimento (chamados / chamados)"
for p in 5432 5433; do
  sudo -u postgres psql -q -p "$p" -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'chamados') THEN
    CREATE ROLE chamados LOGIN PASSWORD 'chamados';
  END IF;
END $$;
-- Os testes em paralelo (pytest -n) criam um banco por worker: chamados_test_gw0, _gw1…
ALTER ROLE chamados CREATEDB;
SQL
done
criar_banco() {
  if [[ -z "$(sudo -u postgres psql -p "$1" -Atc "SELECT 1 FROM pg_database WHERE datname = '$2'")" ]]; then
    sudo -u postgres createdb -p "$1" -O chamados "$2"
    echo "criado: $2 (porta $1)"
  fi
}
criar_banco 5432 chamados
criar_banco 5432 chamados_test
criar_banco 5432 chamados_bench  # o benchmark (backend/bench)
criar_banco 5433 chamados_test

etapa "uv (Python)"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
uv --version

etapa "código em $DESTINO"
if [[ -d "$DESTINO/.git" ]]; then
  echo "já existe: mantido como está (para atualizar: git pull)"
else
  install -d -o "$DEV" -g "$GRUPO_DEV" "$DESTINO"
  como_dev "git clone -q $REPO_HTTPS '$DESTINO'"
fi
if [[ -n "${GIT_NOME:-}" && -n "${GIT_EMAIL:-}" ]]; then
  como_dev "git -C '$DESTINO' config user.name '$GIT_NOME' && git -C '$DESTINO' config user.email '$GIT_EMAIL'"
fi

etapa "dependências, migrações e hook de pre-commit"
como_dev "cd '$DESTINO/backend' && { [[ -f .env ]] || cp .env.example .env; } && uv sync -q && uv run chamados db upgrade"
como_dev "cd '$DESTINO' && scripts/css.sh"
como_dev "cd '$DESTINO' && scripts/install-hooks.sh"

etapa "chave para enviar ao GitHub (deploy key só deste repositório)"
# Busca pelo HTTPS (o repositório é público); envia pelo SSH, com a chave abaixo.
como_dev "mkdir -p ~/.ssh && chmod 700 ~/.ssh
  [[ -f ~/.ssh/ticketflow_github ]] ||
    ssh-keygen -q -t ed25519 -N '' -C \"ticketflow-deploy@\$(hostname)\" -f ~/.ssh/ticketflow_github
  grep -q '^Host github-ticketflow\$' ~/.ssh/config 2>/dev/null ||
    printf '\n# Deploy key do repositório 0LB-i/ticketflow (GitHub)\nHost github-ticketflow\n  HostName github.com\n  User git\n  IdentityFile ~/.ssh/ticketflow_github\n  IdentitiesOnly yes\n' >> ~/.ssh/config
  chmod 600 ~/.ssh/config
  grep -q '^github.com ' ~/.ssh/known_hosts 2>/dev/null ||
    ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null
  git -C '$DESTINO' remote set-url --push origin $REPO_SSH"

if [[ $SERVICO == 1 ]]; then
  etapa "serviço ticketflow.service"
  bash "$DESTINO/scripts/instalar-servico-dev.sh"
fi

CHAVE_PUBLICA="$(como_dev 'cat ~/.ssh/ticketflow_github.pub')"
cat <<FIM

Pronto. Código em $DESTINO (dono: $DEV).

Para rodar (dois terminais), conforme o README:
  cd $DESTINO/backend && uv run uvicorn chamados.main:create_app --factory --reload
                                            # http://localhost:8000, entre com admin / admin
  cd $DESTINO && scripts/css.sh --watch     # o CSS das telas, a cada mudança nos templates
Verificação: $DESTINO/scripts/check.sh   (ou --completo, que usa também o PostgreSQL 16)

Para enviar commits ao GitHub, cadastre esta chave em
https://github.com/0LB-i/ticketflow/settings/keys  →  Add deploy key, marcando "Allow write access":

  $CHAVE_PUBLICA
FIM
if [[ -z "${GIT_NOME:-}" ]]; then
  echo
  echo "Autor dos commits: git -C $DESTINO config user.name 'Seu nome' && git -C $DESTINO config user.email 'voce@exemplo.com'"
fi
