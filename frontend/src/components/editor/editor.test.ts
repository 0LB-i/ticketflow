import type { Editor } from '@tiptap/vue-3'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import { montar, simularApi } from '@/test/setup'

import MarkdownView from './MarkdownView.vue'
import RichEditor from './RichEditor.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const ANEXO = '00000000-0000-0000-0000-0000000000f1'

const PESSOAS = [
  { id: 'u-ana', label: 'Ana Souza' },
  { id: 'u-caio', label: 'Caio Dias' },
]

describe('RichEditor', () => {
  it('carrega e devolve Markdown', async () => {
    const w = montar(RichEditor, {
      props: { label: 'Descrição', modelValue: 'Texto **forte**\n\n- um\n- dois' },
    })
    await vi.waitFor(() => expect(w.find('strong').exists()).toBe(true))
    expect(w.findAll('li')).toHaveLength(2)
    expect(w.get('[role=textbox]').attributes('aria-labelledby')).toBeTruthy()

    await w.setProps({ modelValue: '' })
    await nextTick()
    expect(w.find('strong').exists()).toBe(false)
  })

  it('grava a menção como @Nome e devolve o id do mencionado', async () => {
    const w = montar(RichEditor, { props: { label: 'Comentário', pessoas: PESSOAS } })
    await vi.waitFor(() => expect(w.find('[role=textbox]').exists()).toBe(true))
    const { editor } = (w.vm.$ as unknown as { setupState: { editor: Editor } }).setupState
    editor.commands.insertContent([
      { type: 'text', text: 'Oi ' },
      { type: 'mention', attrs: { id: 'u-caio', label: 'Caio Dias' } },
      { type: 'text', text: ', pode olhar?' },
    ])
    await nextTick()
    const emitido = w.emitted('update:modelValue')!.at(-1)![0] as string
    expect(emitido).toBe('Oi @Caio Dias, pode olhar?')
    expect((w.vm as unknown as { mencionados: () => string[] }).mencionados()).toEqual(['u-caio'])
  })

  it('imagem colada vai para a API e entra no texto como anexo', async () => {
    const feitas = simularApi({
      'POST /api/v1/uploads': [201, { id: ANEXO, filename: 'image.png' }],
    })
    const w = montar(RichEditor, { props: { label: 'Comentário', anexar: true } })
    await vi.waitFor(() => expect(w.find('[role=textbox]').exists()).toBe(true))
    const { editor } = (w.vm.$ as unknown as { setupState: { editor: Editor } }).setupState
    const print = new File([new Uint8Array([137, 80, 78, 71])], 'image.png', { type: 'image/png' })
    const colar = editor.view.props.handlePaste!
    expect(colar(editor.view, { clipboardData: { files: [print] } } as never, null as never)).toBe(
      true,
    )

    await vi.waitFor(() =>
      expect((w.emitted('update:modelValue')!.at(-1)![0] as string).trim()).toBe(
        `![image.png](/api/v1/attachments/${ANEXO})`,
      ),
    )
    expect(feitas[0]!.caminho).toBe('/api/v1/uploads')
    expect(feitas[0]!.corpo).toContain('name="file"') // multipart
    expect(w.find(`img[src="/api/v1/attachments/${ANEXO}"]`).exists()).toBe(true)
  })

  it('sem anexar, colar imagem segue o comportamento padrão', async () => {
    const w = montar(RichEditor, { props: { label: 'Comentário' } })
    await vi.waitFor(() => expect(w.find('[role=textbox]').exists()).toBe(true))
    const { editor } = (w.vm.$ as unknown as { setupState: { editor: Editor } }).setupState
    const print = new File(['x'], 'image.png', { type: 'image/png' })
    expect(
      editor.view.props.handlePaste!(
        editor.view,
        { clipboardData: { files: [print] } } as never,
        null as never,
      ),
    ).toBe(false)
  })
})

describe('MarkdownView', () => {
  it('mostra HTML digitado como texto (sem XSS)', () => {
    const w = montar(MarkdownView, {
      props: { source: '<img src=x onerror="alert(1)"> [link](javascript:alert(1)) **ok**' },
    })
    expect(w.find('img').exists()).toBe(false)
    expect(w.find('a').exists()).toBe(false)
    expect(w.find('strong').text()).toBe('ok')
    expect(w.text()).toContain('<img src=x')
  })

  it('abre links em outra aba', () => {
    const w = montar(MarkdownView, { props: { source: 'veja https://exemplo.com' } })
    expect(w.get('a').attributes()).toMatchObject({
      href: 'https://exemplo.com',
      target: '_blank',
      rel: 'noopener noreferrer',
    })
  })

  it('mostra só as imagens anexadas no próprio sistema', () => {
    const w = montar(MarkdownView, {
      props: {
        source: `![print](/api/v1/attachments/${ANEXO})\n\n![rastreio](https://fora.com/pixel.gif)`,
      },
    })
    const imagens = w.findAll('img')
    expect(imagens).toHaveLength(1)
    expect(imagens[0]!.attributes('src')).toBe(`/api/v1/attachments/${ANEXO}`)
    expect(w.get('a').attributes('href')).toBe(`/api/v1/attachments/${ANEXO}`)
    expect(w.text()).toContain('https://fora.com/pixel.gif')
  })
})
