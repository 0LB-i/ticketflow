<script setup lang="ts">
import { useBrandingStore } from '@/stores/branding'

/**
 * Logotipo: a imagem enviada nas configurações ou o provisório (docs/17 §17.6), um quadrado
 * na cor da marca com "T", seguido do nome do sistema.
 */
const branding = useBrandingStore()
</script>

<template>
  <span class="inline-flex items-center gap-2 text-base font-bold text-fg">
    <img
      v-if="branding.dados?.logo_url"
      :src="branding.dados.logo_url"
      alt=""
      class="h-7 max-w-24 shrink-0 object-contain"
    />
    <svg v-else viewBox="0 0 32 32" class="size-7 shrink-0" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="var(--tf-brand)" />
      <path d="M9 9h14v4h-5v12h-4V13H9z" fill="#fff" />
    </svg>
    {{ $t('app.nome') }}
  </span>
</template>
