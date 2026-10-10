<script setup lang="ts">
import { ref } from 'vue'

import Button from './Button.vue'
import Modal from './Modal.vue'

/** Mostra um link para o administrador copiar e repassar (quando não há SMTP, questão 1). */
defineProps<{ title: string; description: string; url: string }>()
const open = defineModel<boolean>('open', { default: false })
const copiado = ref(false)

async function copiar(url: string) {
  await navigator.clipboard.writeText(url)
  copiado.value = true
  setTimeout(() => (copiado.value = false), 2000)
}
</script>

<template>
  <Modal v-model:open="open" :title="title" :description="description">
    <div class="flex gap-2">
      <input
        :value="url"
        readonly
        :aria-label="title"
        class="h-10 min-w-0 flex-1 rounded-md border border-border-input bg-surface-raised px-3 font-mono text-xs"
        @focus="($event.target as HTMLInputElement).select()"
      />
      <Button variant="secondary" @click="copiar(url)">
        {{ copiado ? $t('comum.copiado') : $t('comum.copiar') }}
      </Button>
    </div>
    <template #actions>
      <Button @click="open = false">{{ $t('comum.fechar') }}</Button>
    </template>
  </Modal>
</template>
