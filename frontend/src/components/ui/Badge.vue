<script setup lang="ts">
export type BadgeCor = 'blue' | 'violet' | 'teal' | 'green' | 'gray' | 'red'

defineProps<{ color: BadgeCor }>()

// Classes completas (não montadas por concatenação) para o Tailwind encontrá-las.
const cores: Record<BadgeCor, string> = {
  blue: 'bg-blue-bg text-blue-fg',
  violet: 'bg-violet-bg text-violet-fg',
  teal: 'bg-teal-bg text-teal-fg',
  green: 'bg-green-bg text-green-fg',
  gray: 'bg-gray-bg text-gray-fg',
  red: 'bg-red-bg text-red-fg',
}
</script>

<template>
  <span
    :class="[
      'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
      cores[color],
    ]"
  >
    <slot />
  </span>
</template>
