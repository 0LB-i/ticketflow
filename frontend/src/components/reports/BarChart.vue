<script setup lang="ts">
import { computed } from 'vue'

/**
 * Barras horizontais de uma série só (horas por pessoa, por cliente): o rótulo à esquerda e o
 * valor na ponta de cada barra. A tabela logo abaixo, na tela, traz os mesmos números.
 */
const props = defineProps<{
  titulo: string
  itens: { chave: string; rotulo: string; valor: number }[]
  formatar: (valor: number) => string
}>()

const maximo = computed(() => Math.max(1, ...props.itens.map((i) => i.valor)))
</script>

<template>
  <figure class="flex flex-col gap-3">
    <figcaption class="font-medium">{{ titulo }}</figcaption>
    <ul class="flex flex-col gap-2">
      <li
        v-for="item in itens"
        :key="item.chave"
        class="grid grid-cols-[minmax(0,10rem)_1fr] items-center gap-3"
      >
        <span class="truncate text-muted" :title="item.rotulo">{{ item.rotulo }}</span>
        <span class="flex items-center gap-2">
          <span
            class="h-4 rounded-r bg-primary"
            :style="{ width: `${(item.valor / maximo) * 85}%` }"
            aria-hidden="true"
          />
          <span class="text-sm whitespace-nowrap tabular-nums">{{ formatar(item.valor) }}</span>
        </span>
      </li>
    </ul>
  </figure>
</template>
