import MarkdownIt from 'markdown-it'

// `html: false`: HTML digitado no texto aparece como texto, nunca vira elemento (sem XSS).
// O markdown-it também recusa links javascript:, vbscript: e data: (exceto imagens).
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

const linkOpen = md.renderer.rules.link_open
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx]!.attrSet('target', '_blank')
  tokens[idx]!.attrSet('rel', 'noopener noreferrer')
  return linkOpen
    ? linkOpen(tokens, idx, options, env, self)
    : self.renderToken(tokens, idx, options)
}

// Imagens só dos anexos do próprio sistema (prints colados no editor). Uma imagem de fora
// seria carregada por quem abre o chamado (rastreamento): aparece só o endereço, como texto.
const ANEXO = /^\/api\/v1\/attachments\/[0-9a-f-]{36}$/
const image = md.renderer.rules.image!
md.renderer.rules.image = (tokens, idx, options, env, self) => {
  const src = String(tokens[idx]!.attrGet('src') ?? '')
  if (!ANEXO.test(src)) return md.utils.escapeHtml(src)
  tokens[idx]!.attrSet('loading', 'lazy')
  const href = md.utils.escapeHtml(src)
  return `<a href="${href}" target="_blank" rel="noopener noreferrer">${image(tokens, idx, options, env, self)}</a>`
}

/** HTML seguro a partir do Markdown gravado nos chamados e comentários. */
export function renderizarMarkdown(texto: string): string {
  return md.render(texto)
}
