<script setup lang="ts">
import Badge, { type BadgeCor } from './Badge.vue'

export type StatusKind = 'open' | 'waiting' | 'approval' | 'delivered' | 'closed' | 'canceled'

/** A cor vem do `kind`; o texto é o nome do status (renomeável pelo admin), docs/10 §10.5. */
defineProps<{ kind: StatusKind; label?: string }>()

const cores: Record<StatusKind, BadgeCor> = {
  open: 'blue',
  waiting: 'violet',
  approval: 'teal',
  delivered: 'teal',
  closed: 'green',
  canceled: 'gray',
}
</script>

<template>
  <Badge :color="cores[kind]">{{ label ?? $t(`status.${kind}`) }}</Badge>
</template>
