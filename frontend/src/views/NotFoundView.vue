<script setup lang="ts">
import { useHead } from '@/composables/useHead'

useHead('naoEncontrado.titulo')
</script>

<template>
  <div class="mx-auto max-w-md py-16 text-center">
    <h1 class="text-xl font-semibold">{{ $t('naoEncontrado.titulo') }}</h1>
    <p class="mt-2 text-muted">{{ $t('naoEncontrado.texto') }}</p>
    <RouterLink to="/" class="mt-6 inline-block font-medium text-primary underline">
      {{ $t('naoEncontrado.voltar') }}
    </RouterLink>
  </div>
</template>
