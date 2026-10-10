<script setup lang="ts">
import { useHead } from '@/composables/useHead'

useHead('semAcesso.titulo')
</script>

<template>
  <div class="mx-auto max-w-md py-16 text-center">
    <h1 class="text-xl font-semibold">{{ $t('semAcesso.titulo') }}</h1>
    <p class="mt-2 text-muted">{{ $t('semAcesso.texto') }}</p>
    <RouterLink to="/" class="mt-6 inline-block font-medium text-primary underline">
      {{ $t('semAcesso.voltar') }}
    </RouterLink>
  </div>
</template>
