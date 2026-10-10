<script setup lang="ts">
import { useId } from 'vue'

/** Opções exclusivas, com rótulo do grupo (fieldset + legend) para leitores de tela. */
defineProps<{
  legend: string
  options: { value: string; label: string }[]
}>()
const model = defineModel<string>()
const nome = useId()
</script>

<template>
  <fieldset class="flex flex-col gap-1">
    <legend class="mb-1 font-medium">{{ legend }}</legend>
    <div class="flex flex-wrap gap-x-5 gap-y-2">
      <label
        v-for="option in options"
        :key="option.value"
        class="inline-flex cursor-pointer items-center gap-2"
      >
        <input
          v-model="model"
          type="radio"
          :name="nome"
          :value="option.value"
          class="size-4 accent-(--tf-primary)"
        />
        {{ option.label }}
      </label>
    </div>
  </fieldset>
</template>
