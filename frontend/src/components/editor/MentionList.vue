<script setup lang="ts">
import { ref, watch } from 'vue'

export interface Pessoa {
  id: string
  label: string
}

/** Lista de sugestões do @ no editor. As setas e o Enter chegam por `onKeyDown`. */
const props = defineProps<{
  items: Pessoa[]
  command: (pessoa: Pessoa) => void
}>()

const ativo = ref(0)
watch(
  () => props.items,
  () => (ativo.value = 0),
)

function escolher(i: number) {
  const pessoa = props.items[i]
  if (pessoa) props.command(pessoa)
}

function onKeyDown(event: KeyboardEvent): boolean {
  const n = props.items.length
  if (!n) return false
  if (event.key === 'ArrowDown') ativo.value = (ativo.value + 1) % n
  else if (event.key === 'ArrowUp') ativo.value = (ativo.value + n - 1) % n
  else if (event.key === 'Enter' || event.key === 'Tab') escolher(ativo.value)
  else return false
  return true
}

defineExpose({ onKeyDown })
</script>

<template>
  <ul
    role="listbox"
    :aria-label="$t('editor.mencionar')"
    class="z-50 max-h-60 min-w-48 overflow-y-auto rounded-md border border-border bg-surface p-1 text-fg shadow-lg"
  >
    <li v-if="!items.length" class="px-2 py-1 text-muted">{{ $t('editor.ninguem') }}</li>
    <li
      v-for="(pessoa, i) in items"
      :key="pessoa.id"
      role="option"
      :aria-selected="i === ativo"
      :class="[
        'cursor-pointer rounded px-2 py-1',
        i === ativo ? 'bg-primary-subtle text-primary' : 'hover:bg-surface-raised',
      ]"
      @mousedown.prevent="escolher(i)"
    >
      {{ pessoa.label }}
    </li>
  </ul>
</template>
