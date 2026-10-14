<script setup lang="ts">
import { LoaderCircle, Paperclip, X } from 'lucide-vue-next'
import { computed, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import Button from '@/components/ui/Button.vue'
import {
  enviarArquivo,
  EXTENSOES_ACEITAS,
  formatarTamanho,
  MAX_POR_ENVIO,
} from '@/composables/anexos'

/**
 * "Anexar" com arrastar e soltar (docs/11 §11.4): cada arquivo vai para a API na hora, e o
 * v-model recebe os ids dos que chegaram, para o formulário mandar em `attachment_ids`.
 * `simples`: só o botão (e a lista), sem a área pontilhada de soltar.
 */
const props = defineProps<{ simples?: boolean }>()
const model = defineModel<string[]>({ default: () => [] })
const { t } = useI18n()
const seletor = useTemplateRef('seletor')

type Item = { chave: number; nome: string; tamanho: number; id?: string; erro?: string }
const itens = ref<Item[]>([])
const arrastando = ref(false)
const aviso = ref<string | null>(null)
let proxima = 0

const enviando = computed(() => itens.value.some((i) => !i.id && !i.erro))

function adicionar(arquivos: FileList | null | undefined) {
  aviso.value = null
  for (const arquivo of arquivos ?? []) {
    if (itens.value.filter((i) => !i.erro).length >= MAX_POR_ENVIO) {
      aviso.value = t('anexos.demais', { n: MAX_POR_ENVIO })
      break
    }
    const chave = ++proxima
    itens.value.push({ chave, nome: arquivo.name, tamanho: arquivo.size })
    // Busca o item de novo na resposta: ele pode ter sido removido enquanto enviava.
    const atual = () => itens.value.find((i) => i.chave === chave)
    enviarArquivo(arquivo)
      .then((anexo) => {
        const item = atual()
        if (!item) return
        item.id = anexo.id
        model.value = [...model.value, anexo.id]
      })
      .catch((e: Error) => {
        const item = atual()
        if (item) item.erro = e.message
      })
  }
}

function remover(item: Item) {
  itens.value = itens.value.filter((i) => i.chave !== item.chave)
  if (item.id) model.value = model.value.filter((id) => id !== item.id)
}

function escolher(evento: Event) {
  const input = evento.target as HTMLInputElement
  adicionar(input.files)
  input.value = ''
}

function soltar(evento: DragEvent) {
  arrastando.value = false
  adicionar(evento.dataTransfer?.files)
}

/** Depois de enviar o formulário: a lista recomeça vazia. */
function limpar() {
  itens.value = []
  model.value = []
  aviso.value = null
}

defineExpose({ enviando, limpar })
</script>

<template>
  <div
    :class="
      props.simples
        ? 'flex flex-col items-end gap-2'
        : [
            'flex flex-col gap-2 rounded-md border border-dashed p-2',
            arrastando ? 'border-primary bg-primary-subtle' : 'border-border-input',
          ]
    "
    @dragover.prevent="arrastando = true"
    @dragleave="arrastando = false"
    @drop.prevent="soltar"
  >
    <div class="flex flex-wrap items-center gap-2">
      <Button variant="secondary" size="sm" @click="seletor?.click()">
        <Paperclip class="size-4" aria-hidden="true" />
        {{ t('anexos.anexar') }}
      </Button>
      <span v-if="!props.simples" class="text-muted">{{ t('anexos.arraste') }}</span>
      <input
        ref="seletor"
        type="file"
        multiple
        class="sr-only"
        tabindex="-1"
        :accept="EXTENSOES_ACEITAS"
        :aria-label="t('anexos.anexar')"
        @change="escolher"
      />
    </div>
    <p v-if="aviso" class="text-danger" role="alert">{{ aviso }}</p>
    <ul v-if="itens.length" class="flex flex-col gap-1" :aria-label="t('anexos.titulo')">
      <li v-for="item in itens" :key="item.chave" class="flex items-center gap-2">
        <LoaderCircle
          v-if="!item.id && !item.erro"
          class="size-4 animate-spin text-muted"
          :aria-label="t('anexos.enviando')"
        />
        <Paperclip v-else class="size-4 text-muted" aria-hidden="true" />
        <span class="min-w-0 truncate">{{ item.nome }}</span>
        <span class="text-muted tabular-nums">{{ formatarTamanho(item.tamanho) }}</span>
        <span v-if="item.erro" class="text-danger">{{ item.erro }}</span>
        <button
          type="button"
          class="ml-auto rounded p-0.5 text-muted hover:bg-surface-raised"
          :aria-label="t('anexos.remover', { nome: item.nome })"
          @click="remover(item)"
        >
          <X class="size-4" aria-hidden="true" />
        </button>
      </li>
    </ul>
  </div>
</template>
