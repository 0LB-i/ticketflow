<script setup lang="ts">
import { FileText, Image } from 'lucide-vue-next'

import { type Anexo, formatarTamanho, urlDoAnexo } from '@/composables/anexos'

/** Anexos de um chamado ou comentário: o link baixa (ou abre, se for imagem ou PDF). */
defineProps<{ anexos: Anexo[] }>()
</script>

<template>
  <ul class="flex flex-col gap-1">
    <li v-for="a in anexos" :key="a.id" class="flex min-w-0 items-center gap-2">
      <component
        :is="a.content_type.startsWith('image/') ? Image : FileText"
        class="size-4 shrink-0 text-muted"
        aria-hidden="true"
      />
      <a
        :href="urlDoAnexo(a.id)"
        target="_blank"
        rel="noopener noreferrer"
        class="min-w-0 truncate text-primary underline"
        >{{ a.filename }}</a
      >
      <span class="shrink-0 text-muted tabular-nums">{{ formatarTamanho(a.size_bytes) }}</span>
    </li>
  </ul>
</template>
