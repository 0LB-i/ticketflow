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

/** Painel lateral de edição das telas de administração (docs/13 §13.5). */
defineProps<{ title: string; description?: string }>()
const open = defineModel<boolean>('open', { default: false })
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-40 bg-black/40" />
      <DialogContent
        class="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-border bg-surface text-fg shadow-xl"
      >
        <div class="flex items-start justify-between gap-4 border-b border-border p-4">
          <div>
            <DialogTitle class="text-lg font-semibold">{{ title }}</DialogTitle>
            <DialogDescription v-if="description" class="mt-1 text-muted">
              {{ description }}
            </DialogDescription>
          </div>
          <DialogClose
            class="rounded p-1 text-muted hover:bg-surface-raised"
            :aria-label="$t('comum.fechar')"
          >
            <X class="size-5" aria-hidden="true" />
          </DialogClose>
        </div>
        <div class="flex-1 overflow-y-auto p-4"><slot /></div>
        <div v-if="$slots.actions" class="flex justify-end gap-2 border-t border-border p-4">
          <slot name="actions" />
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
