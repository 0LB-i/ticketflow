#!/usr/bin/env bash
# Empacota o Tiptap num arquivo só, para o editor das telas do servidor (ADR 0011). O arquivo
# gerado vai para o git: este script só roda para trocar a versão. Precisa de Node.js e internet.
#   scripts/vendor-tiptap.sh
# Depois de trocar a VERSAO, atualize o nome do arquivo nos templates (grep tiptap-).
set -euo pipefail
cd "$(dirname "$0")/.."

VERSAO=3.31.4
ESBUILD=0.25.12
vendor=backend/src/chamados/web/static/js/vendor
destino="$vendor/tiptap-$VERSAO.js"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# O que o static/js/editor.js usa, exposto no objeto global `Tiptap`.
cat >"$tmp/entrada.js" <<'FIM'
export { Editor } from '@tiptap/core'
export { default as StarterKit } from '@tiptap/starter-kit'
export { Markdown } from '@tiptap/markdown'
export { Placeholder } from '@tiptap/extensions'
export { default as Mention } from '@tiptap/extension-mention'
export { default as Image } from '@tiptap/extension-image'
FIM

pacotes=(core pm starter-kit markdown extensions extension-mention extension-image suggestion)
(
  cd "$tmp"
  npm init -y >/dev/null
  npm install --silent --no-audit --no-fund "esbuild@$ESBUILD" \
    $(printf "@tiptap/%s@$VERSAO " "${pacotes[@]}")
)

"$tmp/node_modules/.bin/esbuild" "$tmp/entrada.js" --bundle --minify --format=iife \
  --global-name=Tiptap --legal-comments=eof --target=es2020 --outfile="$destino"
find "$vendor" -name 'tiptap-*.js' ! -name "tiptap-$VERSAO.js" -delete
echo "gerado: $destino ($(du -h "$destino" | cut -f1))"
