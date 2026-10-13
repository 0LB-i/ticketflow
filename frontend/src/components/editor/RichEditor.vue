<script setup lang="ts">
import Image from '@tiptap/extension-image'
import Mention from '@tiptap/extension-mention'
import { Placeholder } from '@tiptap/extensions'
import { Markdown } from '@tiptap/markdown'
import StarterKit from '@tiptap/starter-kit'
import type { SuggestionProps } from '@tiptap/suggestion'
import { EditorContent, useEditor, VueRenderer } from '@tiptap/vue-3'
import { Bold, Italic, List, ListOrdered } from 'lucide-vue-next'
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { enviarArquivo, urlDoAnexo } from '@/composables/anexos'

import MentionList, { type Pessoa } from './MentionList.vue'

/**
 * Editor da descrição e dos comentários (Tiptap, questão 4): grava Markdown no v-model.
 * Com `pessoas`, o @ abre a lista de colegas; `mencionados()` devolve os ids escolhidos,
 * que a API recebe em `mention_ids` (o texto guarda só "@Nome").
 * Com `anexar`, imagens coladas ou arrastadas vão para a API e entram no texto como
 * `![nome](/api/v1/attachments/<id>)`; quem envia o formulário manda esses ids em `attachment_ids`.
 */
const props = defineProps<{
  label: string
  pessoas?: Pessoa[]
  placeholder?: string
  required?: boolean
  error?: string
  /** Área de texto maior, para a descrição no registro. */
  alto?: boolean
  /** Aceita imagens coladas ou arrastadas (prints de tela). */
  anexar?: boolean
}>()
const model = defineModel<string>({ default: '' })
const { t } = useI18n()
const id = useId()

const semAcento = (s: string) =>
  s
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()

const Mencao = Mention.extend({
  renderMarkdown: (node) => `@${node.attrs?.label ?? ''}`,
}).configure({
  HTMLAttributes: { class: 'mencao' },
  renderText: ({ node }) => `@${node.attrs.label}`,
  suggestion: {
    items: ({ query }) =>
      (props.pessoas ?? [])
        .filter((p) => semAcento(p.label).includes(semAcento(query)))
        .slice(0, 8),
    render: () => {
      let lista: VueRenderer | null = null
      const posicionar = (p: SuggestionProps<Pessoa>) => {
        const rect = p.clientRect?.()
        const el = lista?.element as HTMLElement | undefined
        if (!rect || !el) return
        Object.assign(el.style, {
          position: 'fixed',
          left: `${Math.max(8, Math.min(rect.left, window.innerWidth - el.offsetWidth - 8))}px`,
          top: `${rect.bottom + 4}px`,
          zIndex: '50',
        })
      }
      return {
        onStart: (p: SuggestionProps<Pessoa>) => {
          lista = new VueRenderer(MentionList, { props: p, editor: p.editor })
          if (lista.element) document.body.appendChild(lista.element)
          posicionar(p)
        },
        onUpdate: (p: SuggestionProps<Pessoa>) => {
          lista?.updateProps(p)
          posicionar(p)
        },
        onKeyDown: ({ event }: { event: KeyboardEvent }) =>
          event.key === 'Escape'
            ? false
            : ((lista?.ref as { onKeyDown?: (e: KeyboardEvent) => boolean } | null)?.onKeyDown?.(
                event,
              ) ?? false),
        onExit: () => {
          lista?.element?.remove()
          lista?.destroy()
          lista = null
        },
      }
    },
  },
})

// --- imagens coladas ou arrastadas ---
const enviandoImagens = ref(0)
const erroImagem = ref<string | null>(null)
const imagens = (arquivos?: FileList | null) =>
  [...(arquivos ?? [])].filter((f) => f.type.startsWith('image/'))

async function inserirImagens(arquivos: File[]) {
  erroImagem.value = null
  for (const arquivo of arquivos) {
    enviandoImagens.value++
    try {
      const anexo = await enviarArquivo(arquivo)
      editor.value
        ?.chain()
        .focus()
        .setImage({ src: urlDoAnexo(anexo.id), alt: anexo.filename })
        .run()
    } catch (e) {
      erroImagem.value = (e as Error).message
    } finally {
      enviandoImagens.value--
    }
  }
}

let ultimo = model.value
const editor = useEditor({
  content: model.value,
  contentType: 'markdown',
  extensions: [
    StarterKit.configure({ heading: { levels: [2, 3] }, link: { openOnClick: false } }),
    Markdown,
    Placeholder.configure({ placeholder: () => props.placeholder ?? '' }),
    ...(props.pessoas ? [Mencao] : []),
    ...(props.anexar ? [Image] : []),
  ],
  editorProps: {
    attributes: {
      id,
      class: `texto-formatado ${props.alto ? 'min-h-80' : 'min-h-24'} px-3 py-2 outline-none`,
      role: 'textbox',
      'aria-multiline': 'true',
      'aria-labelledby': `${id}-rotulo`,
      ...(props.required ? { 'aria-required': 'true' } : {}),
    },
    handlePaste: (_view, evento) => {
      const lista = imagens(evento.clipboardData?.files)
      if (!props.anexar || !lista.length) return false
      inserirImagens(lista)
      return true
    },
    handleDrop: (view, evento) => {
      const lista = imagens(evento.dataTransfer?.files)
      if (!props.anexar || !lista.length) return false
      const destino = view.posAtCoords({ left: evento.clientX, top: evento.clientY })
      if (destino) editor.value?.commands.setTextSelection(destino.pos)
      inserirImagens(lista)
      return true
    },
  },
  onUpdate: ({ editor }) => {
    ultimo = editor.isEmpty ? '' : editor.getMarkdown()
    model.value = ultimo
  },
})

// Mudança vinda de fora (ex.: limpar depois de enviar).
watch(model, (valor) => {
  if (editor.value && valor !== ultimo) {
    ultimo = valor
    editor.value.commands.setContent(valor, { contentType: 'markdown' })
  }
})

onBeforeUnmount(() => editor.value?.destroy())

function mencionados(): string[] {
  const ids = new Set<string>()
  editor.value?.state.doc.descendants((node) => {
    if (node.type.name === 'mention' && node.attrs.id) ids.add(String(node.attrs.id))
  })
  return [...ids]
}

/** Enquanto houver imagem subindo, o formulário espera. */
const enviando = computed(() => enviandoImagens.value > 0)

defineExpose({ mencionados, enviando })

const botoes = [
  { acao: 'bold', icone: Bold, rotulo: 'editor.negrito', cmd: 'toggleBold' },
  { acao: 'italic', icone: Italic, rotulo: 'editor.italico', cmd: 'toggleItalic' },
  { acao: 'bulletList', icone: List, rotulo: 'editor.lista', cmd: 'toggleBulletList' },
  {
    acao: 'orderedList',
    icone: ListOrdered,
    rotulo: 'editor.listaNumerada',
    cmd: 'toggleOrderedList',
  },
] as const
</script>

<template>
  <div class="flex flex-col gap-1">
    <span :id="`${id}-rotulo`" class="font-medium" @click="editor?.commands.focus()">
      {{ label }}<span v-if="required" class="text-danger" aria-hidden="true"> *</span>
    </span>
    <div
      :class="[
        'rounded-md border bg-surface focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-focus',
        error ? 'border-danger' : 'border-border-input',
      ]"
    >
      <div
        v-if="editor"
        role="toolbar"
        :aria-label="t('editor.formatacao')"
        :aria-controls="id"
        class="flex gap-1 border-b border-border p-1"
      >
        <button
          v-for="b in botoes"
          :key="b.acao"
          type="button"
          :aria-label="t(b.rotulo)"
          :title="t(b.rotulo)"
          :aria-pressed="editor.isActive(b.acao)"
          class="inline-flex size-8 items-center justify-center rounded text-muted hover:bg-surface-raised aria-pressed:bg-primary-subtle aria-pressed:text-primary"
          @click="editor.chain().focus()[b.cmd]().run()"
        >
          <component :is="b.icone" class="size-4" aria-hidden="true" />
        </button>
      </div>
      <EditorContent :editor="editor" />
    </div>
    <p v-if="enviando" class="text-muted" role="status">{{ t('anexos.enviandoImagem') }}</p>
    <p v-if="erroImagem" class="text-danger" role="alert">{{ erroImagem }}</p>
    <p v-if="error" class="text-danger">{{ error }}</p>
  </div>
</template>
