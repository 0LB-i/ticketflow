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

const relativos = new Map<string, Intl.RelativeTimeFormat>()
const UNIDADES: [Intl.RelativeTimeFormatUnit, number][] = [
  ['day', 86_400_000],
  ['hour', 3_600_000],
  ['minute', 60_000],
]

/** Há quanto tempo, na maior unidade que couber ("há 3 dias", "há 15 min"). */
export function formatarHaQuanto(iso: string, agora = Date.now()): string {
  const idioma = idiomaAtual()
  let formato = relativos.get(idioma)
  if (!formato) {
    formato = new Intl.RelativeTimeFormat(idioma, { numeric: 'auto', style: 'short' })
    relativos.set(idioma, formato)
  }
  const passado = Math.max(0, agora - new Date(iso).getTime())
  const [unidade, ms] = UNIDADES.find(([, ms]) => passado >= ms) ?? ['minute', 60_000]
  return formato.format(-Math.floor(passado / ms), unidade)
}

/** Tempo gasto em minutos como "1h30", "2h" ou "45min". */
export function formatarDuracao(minutos: number): string {
  const h = Math.floor(minutos / 60)
  const m = minutos % 60
  if (!h) return `${m}min`
  return m ? `${h}h${String(m).padStart(2, '0')}` : `${h}h`
}

/** Até 1000 horas num andamento, como a API aceita. */
const DURACAO_MAXIMA = 60_000

/**
 * Minutos de um tempo digitado: "1:30", "1h30", "1h 30min", "2h" ou "45min". Vazio dá `null`;
 * o que não se entende (ou zero) dá `undefined`. Número solto é recusado: seriam horas ou minutos?
 */
export function lerDuracao(texto: string): number | null | undefined {
  const s = texto.trim().toLowerCase().replace(/\s+/g, '')
  if (!s) return null
  let minutos: number | undefined
  const hm = /^(\d{1,4}):([0-5]\d)$/.exec(s) ?? /^(\d{1,4})h(?:([0-5]?\d)(?:m|min)?)?$/.exec(s)
  if (hm) minutos = Number(hm[1]) * 60 + Number(hm[2] ?? 0)
  const so = /^(\d{1,5})(?:m|min)$/.exec(s)
  if (so) minutos = Number(so[1])
  return minutos && minutos <= DURACAO_MAXIMA ? minutos : undefined
}
