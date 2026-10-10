<script setup lang="ts">
import { X } from 'lucide-vue-next'
import {
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastRoot,
  ToastTitle,
  ToastViewport,
} from 'reka-ui'

import { useToast } from '@/composables/useToast'

const { avisos, remove } = useToast()
</script>

<template>
  <ToastProvider :duration="5000" swipe-direction="right">
    <ToastRoot
      v-for="aviso in avisos"
      :key="aviso.id"
      :type="aviso.variant === 'error' ? 'foreground' : 'background'"
      :class="[
        'relative rounded-lg border bg-surface p-4 pr-10 text-fg shadow-lg',
        aviso.variant === 'error' ? 'border-danger' : 'border-border',
      ]"
      @update:open="(aberto: boolean) => !aberto && remove(aviso.id)"
    >
      <ToastTitle class="font-semibold">{{ aviso.title }}</ToastTitle>
      <ToastDescription v-if="aviso.description" class="mt-1 text-muted">
        {{ aviso.description }}
      </ToastDescription>
      <ToastClose
        class="absolute top-3 right-3 rounded p-1 text-muted hover:bg-surface-raised"
        :aria-label="$t('comum.fechar')"
      >
        <X class="size-4" aria-hidden="true" />
      </ToastClose>
    </ToastRoot>
    <ToastViewport
      class="fixed right-0 bottom-0 z-50 flex w-full max-w-sm flex-col gap-2 p-4 outline-none"
    />
  </ToastProvider>
</template>
