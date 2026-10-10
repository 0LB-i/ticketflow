import { idiomaAtual } from '@/i18n'

const formatos = new Map<string, Intl.DateTimeFormat>()

/** Data e hora absolutas no idioma atual, no fuso de São Paulo (docs/13 §13.6). */
export function formatarDataHora(iso: string | null | undefined): string | null {
  if (!iso) return null
  const idioma = idiomaAtual()
  let formato = formatos.get(idioma)
  if (!formato) {
    formato = new Intl.DateTimeFormat(idioma, {
      dateStyle: 'short',
      timeStyle: 'short',
      timeZone: 'America/Sao_Paulo',
    })
    formatos.set(idioma, formato)
  }
  return formato.format(new Date(iso))
}
