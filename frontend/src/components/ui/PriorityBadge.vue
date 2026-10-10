<script setup lang="ts">
import Badge, { type BadgeCor } from './Badge.vue'

export type Prioridade = 1 | 2 | 3 | 4

/** Cor + ícone + texto: a cor nunca é a única pista (docs/17 §17.2). */
defineProps<{ priority: Prioridade }>()

const estilos: Record<Prioridade, { cor: BadgeCor; icone: string }> = {
  1: { cor: 'gray', icone: '▽' },
  2: { cor: 'blue', icone: '◇' },
  3: { cor: 'red', icone: '△' },
  4: { cor: 'critical', icone: '▲' },
}
</script>

<template>
  <Badge :color="estilos[priority].cor">
    <span aria-hidden="true">{{ estilos[priority].icone }}</span>
    {{ $t(`prioridade.${priority}`) }}
  </Badge>
</template>
