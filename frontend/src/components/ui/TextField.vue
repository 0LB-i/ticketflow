<script setup lang="ts">
import { computed, nextTick, ref, useId } from 'vue'

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
const campo = ref<HTMLInputElement>()

// Quando a máscara do formulário recusa o que foi digitado (letra num CPF, 12º número), o valor
// volta a ser o anterior, o Vue não vê mudança e o campo continuaria mostrando o que foi recusado.
async function conferir() {
  await nextTick()
  if (campo.value && campo.value.value !== model.value) campo.value.value = model.value
}
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
      ref="campo"
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
      @input="conferir"
    />
    <p v-if="hint" :id="`${id}-dica`" class="text-muted">{{ hint }}</p>
    <p v-if="error" :id="`${id}-erro`" class="text-danger">{{ error }}</p>
  </div>
</template>
