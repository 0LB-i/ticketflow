import type { Evento } from '@/composables/chamados'

type Ref = { id: string | number; name: string } | null | undefined
type T = (chave: string, params?: Record<string, unknown>) => string

/** Frase da linha do tempo para um evento do histórico (ticket_events). */
export function descreverEvento(e: Evento, t: T): string {
  const ator = e.actor?.full_name ?? t('evento.sistema')
  const p = e.payload as Record<string, unknown>
  const de = (p.from as Ref)?.name
  const para = (p.to as Ref)?.name
  const pessoa = p.user as Ref
  const ehOAtor = (r: Ref) => r != null && r.id === e.actor?.id

  switch (e.type) {
    case 'ticket.created':
      return t('evento.registrou', { ator })
    case 'ticket.assigned':
      if (!p.to) return t('evento.devolveu', { ator })
      return ehOAtor(p.to as Ref)
        ? t('evento.assumiu', { ator })
        : t('evento.atribuiu', { ator, para })
    case 'ticket.transferred':
      return t('evento.transferiu', { ator, de, para })
    case 'ticket.status_changed': {
      const codigo = (p.resolution_code as Ref)?.name
      const frase = t('evento.mudouStatus', { ator, de, para })
      return codigo ? `${frase} · ${codigo}` : frase
    }
    case 'ticket.updated': {
      const campos = Object.keys((p.changes as object) ?? {})
        .filter((c) => c !== 'priority_overridden')
        .map((c) => t(`evento.campos.${c}`))
      const frase = t('evento.alterou', { ator, campos: campos.join(', ') })
      return p.reason ? `${frase} · ${t('evento.motivo', { motivo: p.reason })}` : frase
    }
    case 'watcher.added':
      if (p.kind === 'mentioned') return t('evento.mencionou', { ator, pessoa: pessoa?.name })
      return ehOAtor(pessoa)
        ? t('evento.passouAAcompanhar', { ator })
        : t('evento.adicionouObservador', { ator, pessoa: pessoa?.name })
    case 'watcher.removed':
      return ehOAtor(pessoa)
        ? t('evento.deixouDeAcompanhar', { ator })
        : t('evento.removeuObservador', { ator, pessoa: pessoa?.name })
    case 'comment.edited':
      return t('evento.editouComentario', { ator })
    default:
      return t('evento.outro', { ator })
  }
}
