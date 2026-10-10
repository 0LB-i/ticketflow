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

/** HTML seguro a partir do Markdown gravado nos chamados e comentários. */
export function renderizarMarkdown(texto: string): string {
  return md.render(texto)
}
