<script setup lang="ts">
/** `ocultarRotulo`: o rótulo fica só para leitores de tela (ex.: a caixa de cada linha). */
defineProps<{ label: string; ocultarRotulo?: boolean }>()
const model = defineModel<boolean>({ default: false })
</script>

<template>
  <label class="inline-flex cursor-pointer items-center gap-2">
    <input v-model="model" type="checkbox" class="size-4 accent-(--tf-primary)" />
    <span :class="{ 'sr-only': ocultarRotulo }">{{ label }}</span>
  </label>
</template>
