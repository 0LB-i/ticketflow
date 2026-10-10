<script setup lang="ts">
import { computed, useId } from 'vue'

const props = defineProps<{
  label: string
  hint?: string
  error?: string
  required?: boolean
  type?: string
  autocomplete?: string
}>()
const model = defineModel<string>({ default: '' })

const id = useId()
const describedBy = computed(
  () =>
    [props.hint && `${id}-dica`, props.error && `${id}-erro`].filter(Boolean).join(' ') ||
    undefined,
)
</script>

<template>
  <div class="flex flex-col gap-1">
    <label :for="id" class="font-medium">
      {{ label }}<span v-if="required" class="text-danger" aria-hidden="true"> *</span>
    </label>
    <input
      :id="id"
      v-model="model"
      :type="type ?? 'text'"
      :required="required"
      :autocomplete="autocomplete"
      :aria-invalid="error ? true : undefined"
      :aria-describedby="describedBy"
      :class="[
        'h-10 rounded-md border bg-surface px-3 text-fg placeholder:text-muted',
        error ? 'border-danger' : 'border-border-input',
      ]"
    />
    <p v-if="hint" :id="`${id}-dica`" class="text-muted">{{ hint }}</p>
    <p v-if="error" :id="`${id}-erro`" class="text-danger">{{ error }}</p>
  </div>
</template>
