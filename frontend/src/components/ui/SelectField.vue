<script setup lang="ts">
import { Check, ChevronDown } from 'lucide-vue-next'
import {
  SelectContent,
  SelectIcon,
  SelectItem,
  SelectItemIndicator,
  SelectItemText,
  SelectPortal,
  SelectRoot,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from 'reka-ui'
import { useId } from 'vue'

defineProps<{
  label: string
  options: { value: string; label: string }[]
  placeholder?: string
}>()
const model = defineModel<string>()
const id = useId()
</script>

<template>
  <div class="flex flex-col gap-1">
    <label :for="id" class="font-medium">{{ label }}</label>
    <SelectRoot v-model="model">
      <SelectTrigger
        :id="id"
        class="inline-flex h-10 items-center justify-between gap-2 rounded-md border border-border-input bg-surface px-3 text-left text-fg data-placeholder:text-muted"
      >
        <SelectValue :placeholder="placeholder ?? $t('comum.selecione')" />
        <SelectIcon><ChevronDown class="size-4 text-muted" aria-hidden="true" /></SelectIcon>
      </SelectTrigger>
      <SelectPortal>
        <SelectContent
          position="popper"
          :side-offset="4"
          class="z-50 min-w-(--reka-select-trigger-width) rounded-md border border-border bg-surface p-1 text-fg shadow-lg"
        >
          <SelectViewport>
            <SelectItem
              v-for="option in options"
              :key="option.value"
              :value="option.value"
              class="relative flex h-8 cursor-default items-center rounded px-2 pl-7 outline-none select-none data-highlighted:bg-surface-raised"
            >
              <SelectItemIndicator class="absolute left-2">
                <Check class="size-4" aria-hidden="true" />
              </SelectItemIndicator>
              <SelectItemText>{{ option.label }}</SelectItemText>
            </SelectItem>
          </SelectViewport>
        </SelectContent>
      </SelectPortal>
    </SelectRoot>
  </div>
</template>
