<script setup lang="ts">
import { useId } from 'vue'

defineProps<{ label: string; hint?: string; required?: boolean; rows?: number }>()
const model = defineModel<string>({ default: '' })
const id = useId()
</script>

<template>
  <div class="flex flex-col gap-1">
    <label :for="id" class="font-medium">
      {{ label }}<span v-if="required" class="text-danger" aria-hidden="true"> *</span>
    </label>
    <textarea
      :id="id"
      v-model="model"
      :rows="rows ?? 3"
      :required="required"
      :aria-describedby="hint ? `${id}-dica` : undefined"
      class="rounded-md border border-border-input bg-surface px-3 py-2 text-fg"
    />
    <p v-if="hint" :id="`${id}-dica`" class="text-muted">{{ hint }}</p>
  </div>
</template>
