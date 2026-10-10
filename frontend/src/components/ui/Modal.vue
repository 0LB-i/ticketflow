<script setup lang="ts">
import { X } from 'lucide-vue-next'
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'

defineProps<{ title: string; description?: string }>()
const open = defineModel<boolean>('open', { default: false })
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-40 bg-black/50" />
      <DialogContent
        class="fixed top-1/2 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface p-6 text-fg shadow-xl"
      >
        <DialogTitle class="text-lg font-semibold">{{ title }}</DialogTitle>
        <DialogDescription v-if="description" class="mt-2 text-muted">
          {{ description }}
        </DialogDescription>
        <div class="mt-4"><slot /></div>
        <div v-if="$slots.actions" class="mt-6 flex justify-end gap-2">
          <slot name="actions" />
        </div>
        <DialogClose
          class="absolute top-4 right-4 rounded p-1 text-muted hover:bg-surface-raised"
          :aria-label="$t('comum.fechar')"
        >
          <X class="size-4" aria-hidden="true" />
        </DialogClose>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
