#!/usr/bin/env bash
# Instala o hook de pre-commit que roda a verificação rápida (docs/12 §12.3).
set -euo pipefail
cd "$(dirname "$0")/.."
hook=.git/hooks/pre-commit
cat > "$hook" <<'HOOK'
#!/usr/bin/env bash
exec scripts/check.sh --rapido
HOOK
chmod +x "$hook"
echo "Hook instalado em $hook"
