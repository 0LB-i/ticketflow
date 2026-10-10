import { idiomaAtual } from '@/i18n'

/** Fuso em que datas e horas aparecem e são digitadas (docs/13 §13.6). */
const FUSO = 'America/Sao_Paulo'

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
      timeZone: FUSO,
    })
    formatos.set(idioma, formato)
  }
  return formato.format(new Date(iso))
}

const partes = new Intl.DateTimeFormat('en-CA', {
  timeZone: FUSO,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** Data ("2026-10-10") e hora ("14:30") de um instante no fuso de São Paulo, como os inputs usam. */
export function dataEHora(instante: Date): { data: string; hora: string } {
  const p = Object.fromEntries(partes.formatToParts(instante).map((x) => [x.type, x.value]))
  return { data: `${p.year}-${p.month}-${p.day}`, hora: `${p.hour}:${p.minute}` }
}

/** Instante de uma data e hora digitadas no fuso de São Paulo (o inverso de `dataEHora`). */
export function instante(data: string, hora: string): Date {
  const utc = (d: string, h: string) => {
    const [ano, mes, dia] = d.split('-').map(Number)
    const [hh, mm] = h.split(':').map(Number)
    return Date.UTC(ano!, mes! - 1, dia!, hh!, mm!)
  }
  const comoUtc = utc(data, hora)
  const noFuso = dataEHora(new Date(comoUtc))
  return new Date(comoUtc - (utc(noFuso.data, noFuso.hora) - comoUtc))
}
