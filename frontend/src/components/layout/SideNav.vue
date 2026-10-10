<script setup lang="ts">
import { House, LayoutGrid } from 'lucide-vue-next'

defineEmits<{ navigate: [] }>()

const itens = [
  { to: '/', rotulo: 'menu.inicio', icone: House },
  ...(import.meta.env.DEV
    ? [{ to: '/dev/componentes', rotulo: 'menu.componentes', icone: LayoutGrid }]
    : []),
]
</script>

<template>
  <nav :aria-label="$t('menu.titulo')" class="flex flex-col gap-1 p-3">
    <RouterLink
      v-for="item in itens"
      :key="item.to"
      :to="item.to"
      class="flex h-10 items-center gap-3 rounded-md px-3 font-medium text-fg hover:bg-surface-raised"
      exact-active-class="bg-primary-subtle text-primary"
      @click="$emit('navigate')"
    >
      <component :is="item.icone" class="size-5" aria-hidden="true" />
      {{ $t(item.rotulo) }}
    </RouterLink>
  </nav>
</template>
