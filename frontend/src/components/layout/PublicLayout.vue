<script setup lang="ts">
import AppLogo from './AppLogo.vue'
import ThemeMenu from './ThemeMenu.vue'

/** Telas sem login (entrar, esqueci a senha, convite): cartão centralizado. */
</script>

<template>
  <div class="flex min-h-dvh flex-col">
    <div class="flex justify-end p-2"><ThemeMenu /></div>
    <main class="flex flex-1 items-start justify-center px-4 pt-8 pb-16 sm:pt-16">
      <div class="w-full max-w-sm">
        <div class="mb-6 flex justify-center"><AppLogo /></div>
        <div class="rounded-lg border border-border bg-surface p-6 shadow-sm">
          <slot />
        </div>
      </div>
    </main>
  </div>
</template>
