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

/** Tempo gasto em minutos como o campo mostra: "01:30". */
export function formatarHoraMinuto(minutos: number): string {
  const h = String(Math.floor(minutos / 60)).padStart(2, '0')
  return `${h}:${String(minutos % 60).padStart(2, '0')}`
}

/** Horários da lista do campo: 20 e 30 min, de 15 em 15 até 3 h, de hora em hora até 24 h. */
export const TEMPOS_SUGERIDOS: number[] = [
  20,
  30,
  ...Array.from({ length: 10 }, (_, i) => 45 + i * 15),
  ...Array.from({ length: 21 }, (_, i) => (4 + i) * 60),
]

/**
 * Máscara hh:mm: os números entram pela direita, como numa calculadora ("130" → "01:30",
 * "45" → "00:45"). Sem números, fica vazio.
 */
export function mascararHoraMinuto(texto: string): string {
  const numeros = texto.replace(/\D/g, '').replace(/^0+/, '').slice(-4)
  if (!numeros) return ''
  const n = numeros.padStart(4, '0')
  return `${n.slice(0, 2)}:${n.slice(2)}`
}

/** Minutos de um "hh:mm". Vazio dá `null`; minutos acima de 59 ou zero dão `undefined`. */
export function lerDuracao(texto: string): number | null | undefined {
  if (!texto) return null
  const hm = /^(\d{2}):(\d{2})$/.exec(texto)
  if (!hm || Number(hm[2]) > 59) return undefined
  return Number(hm[1]) * 60 + Number(hm[2]) || undefined
}
