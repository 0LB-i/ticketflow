import { afterEach, describe, expect, it, vi } from 'vitest'

import { montar, simularApi } from '@/test/setup'

import AttachmentUploader from './AttachmentUploader.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const ID = '00000000-0000-0000-0000-0000000000f1'

function escolherArquivos(w: ReturnType<typeof montar>, arquivos: File[]) {
  const input = w.get('input[type=file]')
  Object.defineProperty(input.element, 'files', { value: arquivos, configurable: true })
  return input.trigger('change')
}

describe('AttachmentUploader', () => {
  it('envia cada arquivo na hora e guarda os ids que chegaram', async () => {
    let n = 0
    simularApi({
      'POST /api/v1/uploads': () =>
        ++n === 1
          ? [201, { id: ID, filename: 'contrato.pdf' }]
          : [422, { detail: 'Tipo de arquivo não permitido.' }],
    })
    const w = montar(AttachmentUploader, { props: { modelValue: [] } })
    await escolherArquivos(w, [
      new File(['%PDF-'], 'contrato.pdf', { type: 'application/pdf' }),
      new File(['MZ'], 'programa.exe'),
    ])

    await vi.waitFor(() => expect(w.text()).toContain('Tipo de arquivo não permitido.'))
    expect(w.emitted('update:modelValue')!.at(-1)).toEqual([[ID]])
    expect(w.text()).toContain('contrato.pdf')

    await w.get('[aria-label="Remover contrato.pdf"]').trigger('click')
    expect(w.emitted('update:modelValue')!.at(-1)).toEqual([[]])
    expect(w.text()).not.toContain('contrato.pdf')
  })

  it('aceita no máximo 10 arquivos por envio', async () => {
    simularApi({ 'POST /api/v1/uploads': [201, { id: ID }] })
    const w = montar(AttachmentUploader, { props: { modelValue: [] } })
    await escolherArquivos(
      w,
      Array.from({ length: 11 }, (_, i) => new File(['x'], `nota${i}.txt`)),
    )
    expect(w.findAll('li')).toHaveLength(10)
    expect(w.text()).toContain('No máximo 10 arquivos por envio.')
  })
})
