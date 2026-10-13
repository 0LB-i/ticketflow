import { api, ou, type Schemas } from '@/api/client'
import { i18n, idiomaAtual } from '@/i18n'

export type Anexo = Schemas['AttachmentOut']

/** Extensões aceitas pela API (docs/11 §11.2), para o seletor de arquivos já filtrar. */
export const EXTENSOES_ACEITAS = [
  'png',
  'jpg',
  'jpeg',
  'gif',
  'webp',
  'heic',
  'pdf',
  'docx',
  'xlsx',
  'pptx',
  'odt',
  'ods',
  'odp',
  'msg',
  'rtf',
  'eml',
  'txt',
  'log',
  'csv',
  'md',
  'json',
  'xml',
  'yaml',
  'yml',
]
  .map((e) => `.${e}`)
  .join(',')
export const MAX_POR_ENVIO = 10

export const urlDoAnexo = (id: string) => `/api/v1/attachments/${id}`
const NO_TEXTO =
  /\/api\/v1\/attachments\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/g

/** Ids dos anexos citados num texto Markdown (as imagens coladas no editor). */
export function anexosNoTexto(texto: string): string[] {
  return [...new Set([...texto.matchAll(NO_TEXTO)].map((m) => m[1]!))]
}

/** 1ª etapa do envio (docs/11 §11.4): o arquivo vai antes do formulário. */
export async function enviarArquivo(arquivo: File): Promise<Anexo> {
  return ou(
    await api.POST('/api/v1/uploads', {
      // O tipo gerado diz "string" (binário); o que vai é o próprio arquivo, num FormData.
      body: { file: arquivo as unknown as string },
      bodySerializer: () => {
        const dados = new FormData()
        dados.append('file', arquivo)
        return dados
      },
    }),
    i18n.global.t('comum.erroInesperado'),
  )
}

export function formatarTamanho(bytes: number): string {
  const formato = new Intl.NumberFormat(idiomaAtual(), { maximumFractionDigits: 1 })
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${formato.format(bytes / 1024)} KB`
  return `${formato.format(bytes / 1024 / 1024)} MB`
}
