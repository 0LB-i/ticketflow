/**
 * Paleta da interface a partir das 3 cores escolhidas pelo administrador (docs/17 §17.2):
 * marca (laranja), neutra (cinza) e fundo (branco). Os tons são ajustados automaticamente
 * para manter o contraste mínimo da WCAG 2.1 AA (docs/17 §17.3): 4,5:1 para texto e 3:1 para
 * bordas de campos e contorno de foco. Sem personalização, vale a paleta original do docs/17.
 */

export interface Cores {
  brand: string
  neutral: string
  background: string
}

/** Tokens de cor (variáveis --tf-*) que dependem das 3 cores. */
export type Tokens = Record<(typeof TOKENS)[number], string>
export interface Paleta {
  claro: Tokens
  escuro: Tokens
}

export const TOKENS = [
  'brand',
  'primary',
  'primary-hover',
  'on-primary',
  'primary-subtle',
  'focus',
  'bg',
  'surface',
  'surface-raised',
  'fg',
  'muted',
  'border',
  'border-input',
] as const

export const CORES_PADRAO: Cores = { brand: '#F97316', neutral: '#737373', background: '#FFFFFF' }

/**
 * Combinações prontas da tela de Configurações; a primeira é o padrão. Sem vermelho nem rosa
 * na marca: confundiriam com o botão destrutivo e a prioridade alta (docs/17 §17.2).
 */
export const PREDEFINIDAS: { id: string; cores: Cores }[] = [
  { id: 'padrao', cores: CORES_PADRAO },
  { id: 'azul', cores: { brand: '#2563EB', neutral: '#64748B', background: '#FFFFFF' } },
  { id: 'verde', cores: { brand: '#16A34A', neutral: '#71717A', background: '#FFFFFF' } },
  { id: 'petroleo', cores: { brand: '#0D9488', neutral: '#64748B', background: '#FFFFFF' } },
  { id: 'roxo', cores: { brand: '#7C3AED', neutral: '#71717A', background: '#FFFFFF' } },
  { id: 'ambar', cores: { brand: '#D97706', neutral: '#78716C', background: '#FFFBF5' } },
  { id: 'grafite', cores: { brand: '#374151', neutral: '#6B7280', background: '#F9FAFB' } },
]

/** Paleta original, escolhida à mão (docs/17 §17.2 e assets/main.css). */
export const PALETA_PADRAO: Paleta = {
  claro: {
    brand: '#F97316',
    primary: '#C2410C',
    'primary-hover': '#9A3412',
    'on-primary': '#FFFFFF',
    'primary-subtle': '#FFF7ED',
    focus: '#EA580C',
    bg: '#FAFAFA',
    surface: '#FFFFFF',
    'surface-raised': '#F5F5F5',
    fg: '#171717',
    muted: '#525252',
    border: '#E5E5E5',
    'border-input': '#737373',
  },
  escuro: {
    brand: '#F97316',
    primary: '#FB923C',
    'primary-hover': '#FDBA74',
    'on-primary': '#0A0A0A',
    'primary-subtle': '#262626',
    focus: '#FB923C',
    bg: '#0A0A0A',
    surface: '#171717',
    'surface-raised': '#262626',
    fg: '#F5F5F5',
    muted: '#A3A3A3',
    border: '#262626',
    'border-input': '#737373',
  },
}

// --- conversões: hex ↔ sRGB ↔ OKLCH (espaço perceptual: mexer só na luminosidade L
// mantém o "mesmo" matiz) ---------------------------------------------------------------------

type Rgb = [number, number, number] // 0–1, sRGB
interface Oklch {
  l: number
  c: number
  h: number
}

function hexParaRgb(hex: string): Rgb {
  const n = parseInt(hex.slice(1), 16)
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]
}

function rgbParaHex(rgb: Rgb): string {
  return (
    '#' +
    rgb
      .map((v) =>
        Math.round(Math.min(1, Math.max(0, v)) * 255)
          .toString(16)
          .padStart(2, '0'),
      )
      .join('')
      .toUpperCase()
  )
}

const linear = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
const gama = (v: number) => (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055)

function rgbParaOklch(rgb: Rgb): Oklch {
  const [r, g, b] = rgb.map(linear) as Rgb
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
  return { l: L, c: Math.hypot(A, B), h: Math.atan2(B, A) }
}

function oklchParaRgbBruto({ l: L, c, h }: Oklch): Rgb {
  const A = c * Math.cos(h)
  const B = c * Math.sin(h)
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3
  return [
    gama(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    gama(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    gama(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ]
}

/** Converte para hex; fora da faixa de cores da tela, reduz a saturação até caber. */
function oklchParaHex(cor: Oklch): string {
  const cabe = (rgb: Rgb) => rgb.every((v) => v >= -1e-4 && v <= 1 + 1e-4)
  let rgb = oklchParaRgbBruto(cor)
  if (!cabe(rgb)) {
    let [lo, hi] = [0, cor.c]
    for (let i = 0; i < 20; i++) {
      const meio = (lo + hi) / 2
      if (cabe(oklchParaRgbBruto({ ...cor, c: meio }))) lo = meio
      else hi = meio
    }
    rgb = oklchParaRgbBruto({ ...cor, c: lo })
  }
  return rgbParaHex(rgb)
}

// --- contraste (WCAG 2.1) -------------------------------------------------------------------

function luminancia(hex: string): number {
  const [r, g, b] = hexParaRgb(hex).map(linear) as Rgb
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contraste(a: string, b: string): number {
  const [x, y] = [luminancia(a), luminancia(b)].sort((p, q) => q - p) as [number, number]
  return (x + 0.05) / (y + 0.05)
}

/**
 * Escurece (sobre fundos claros) ou clareia (sobre escuros) a cor, mantendo o matiz, até ter
 * o contraste mínimo com todos os fundos. Se já tem, fica como está.
 */
function legivel(hex: string, fundos: string[], minimo: number): string {
  const ok = (h: string) => fundos.every((f) => contraste(h, f) >= minimo)
  if (ok(hex)) return hex
  const claros = Math.max(...fundos.map(luminancia)) > 0.18
  const base = rgbParaOklch(hexParaRgb(hex))
  for (let passo = 1; passo <= 200; passo++) {
    const l = base.l + (claros ? -1 : 1) * passo * 0.005
    if (l <= 0 || l >= 1) break
    const candidato = oklchParaHex({ ...base, l })
    if (ok(candidato)) return candidato
  }
  return claros ? '#000000' : '#FFFFFF'
}

/** Mesmo matiz da cor, com a luminosidade e a saturação (limitada) indicadas. */
function tom(hex: string, l: number, cMax: number): string {
  const base = rgbParaOklch(hexParaRgb(hex))
  return oklchParaHex({ l, c: Math.min(base.c, cMax), h: base.h })
}

function deslocar(hex: string, delta: number): string {
  const base = rgbParaOklch(hexParaRgb(hex))
  return oklchParaHex({ ...base, l: Math.min(1, Math.max(0, base.l + delta)) })
}

const ESCURO_TEXTO = '#0A0A0A'
const BRANCO = '#FFFFFF'

function derivar(cores: Cores, modo: 'claro' | 'escuro'): Tokens {
  const { brand, neutral } = cores
  let surface: string, bg: string, raised: string, border: string
  if (modo === 'claro') {
    // O fundo escolhido vale só no modo claro; no escuro, os fundos saem da cor neutra.
    surface = cores.background
    const l = rgbParaOklch(hexParaRgb(surface)).l
    const sentido = l > 0.6 ? -1 : 1
    bg = deslocar(surface, sentido * 0.015)
    raised = deslocar(surface, sentido * 0.035)
    border = deslocar(surface, sentido * 0.1)
  } else {
    bg = tom(neutral, 0.145, 0.015)
    surface = tom(neutral, 0.205, 0.015)
    raised = tom(neutral, 0.269, 0.015)
    border = raised
  }
  const fundosClaros = luminancia(surface) > 0.18
  const fundos = [bg, surface, raised]

  const fg = legivel(tom(neutral, fundosClaros ? 0.205 : 0.97, 0.02), fundos, 7)
  const muted = legivel(neutral, fundos, 4.5)
  const borderInput = legivel(neutral, [surface, bg], 3)

  const subtle = fundosClaros
    ? tom(brand, Math.min(0.975, rgbParaOklch(hexParaRgb(surface)).l - 0.02), 0.03)
    : tom(brand, 0.269, 0.02)
  // O texto sobre o botão é branco nos fundos claros e quase preto nos escuros.
  const onPrimary = fundosClaros ? BRANCO : ESCURO_TEXTO
  // Primária: legível como texto (links, item de menu ativo) e com o texto do botão por cima.
  const primary = legivel(brand, [...fundos, subtle, onPrimary], 4.5)
  const hover = legivel(deslocar(primary, fundosClaros ? -0.07 : 0.07), [onPrimary], 4.5)
  const focus = legivel(brand, [surface, bg], 3)

  return {
    brand,
    primary,
    'primary-hover': hover,
    'on-primary': onPrimary,
    'primary-subtle': subtle,
    focus,
    bg,
    surface,
    'surface-raised': raised,
    fg,
    muted,
    border,
    'border-input': borderInput,
  }
}

const iguais = (a: Cores, b: Cores) =>
  (['brand', 'neutral', 'background'] as const).every(
    (k) => a[k].toUpperCase() === b[k].toUpperCase(),
  )

export function paleta(cores: Cores | null): Paleta {
  if (!cores || iguais(cores, CORES_PADRAO)) return PALETA_PADRAO
  return { claro: derivar(cores, 'claro'), escuro: derivar(cores, 'escuro') }
}

/** Variáveis CSS (--tf-*) de um modo, para o atributo style de uma prévia. */
export function variaveis(tokens: Tokens): Record<string, string> {
  return Object.fromEntries(TOKENS.map((t) => [`--tf-${t}`, tokens[t]]))
}

/**
 * Folha de estilo que sobrepõe os tokens do main.css. `html:root` e `html.dark` têm
 * especificidade maior que `:root` e `.dark`, então valem em qualquer ordem no <head>.
 */
export function folhaDeEstilo(p: Paleta): string {
  const regras = (tokens: Tokens) => TOKENS.map((t) => `--tf-${t}:${tokens[t]}`).join(';')
  return `html:root{${regras(p.claro)}}html.dark{${regras(p.escuro)}}`
}
