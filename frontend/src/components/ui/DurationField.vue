<script setup lang="ts">
import { ChevronDown } from 'lucide-vue-next'
import {
  ComboboxAnchor,
  ComboboxContent,
  ComboboxInput,
  ComboboxItem,
  ComboboxPortal,
  ComboboxRoot,
  ComboboxTrigger,
  ComboboxViewport,
} from 'reka-ui'
import { computed, nextTick, ref, useId } from 'vue'

import { formatarHoraMinuto, mascararHoraMinuto, TEMPOS_SUGERIDOS } from '@/composables/formato'

/**
 * Tempo em horas e minutos ("01:30"): digitado com a máscara hh:mm ou escolhido na lista de
 * horários sugeridos. O valor é o texto; `lerDuracao` o converte em minutos.
 */
const props = defineProps<{ label: string; error?: string }>()
const model = defineModel<string>({ default: '' })
const id = useId()
const opcoes = TEMPOS_SUGERIDOS.map(formatarHoraMinuto)

const campo = ref<{ $el: HTMLInputElement }>()
const texto = computed({
  get: () => model.value,
  set: async (valor: string) => {
    model.value = mascararHoraMinuto(valor)
    // Se a máscara recusou o que foi digitado (uma letra), o campo volta ao valor anterior.
    await nextTick()
    const input = campo.value?.$el
    if (input && input.value !== model.value) input.value = model.value
  },
})
const describedBy = computed(() => (props.error ? `${id}-erro` : undefined))
</script>

<template>
  <div class="flex flex-col gap-1">
    <label :for="id" class="font-medium">{{ label }}</label>
    <ComboboxRoot v-model="model" ignore-filter open-on-click :reset-search-term-on-blur="false">
      <ComboboxAnchor
        :class="[
          'inline-flex h-10 items-center gap-1 rounded-md border bg-surface pr-1 pl-3',
          error ? 'border-danger' : 'border-border-input',
        ]"
      >
        <ComboboxInput
          :id="id"
          ref="campo"
          v-model="texto"
          inputmode="numeric"
          placeholder="00:00"
          :aria-invalid="error ? true : undefined"
          :aria-describedby="describedBy"
          class="h-full min-w-0 flex-1 bg-transparent text-fg tabular-nums outline-none placeholder:text-muted"
        />
        <ComboboxTrigger class="rounded p-1 text-muted" :aria-label="label">
          <ChevronDown class="size-4" aria-hidden="true" />
        </ComboboxTrigger>
      </ComboboxAnchor>
      <ComboboxPortal>
        <ComboboxContent
          position="popper"
          :side-offset="4"
          class="z-50 max-h-[min(18rem,var(--reka-combobox-content-available-height))] w-(--reka-combobox-trigger-width) overflow-y-auto rounded-md border border-border bg-surface p-1 text-fg shadow-lg"
        >
          <ComboboxViewport>
            <ComboboxItem
              v-for="o in opcoes"
              :key="o"
              :value="o"
              class="flex h-8 cursor-default items-center rounded px-2 tabular-nums outline-none select-none data-highlighted:bg-surface-raised data-[state=checked]:font-semibold"
            >
              {{ o }}
            </ComboboxItem>
          </ComboboxViewport>
        </ComboboxContent>
      </ComboboxPortal>
    </ComboboxRoot>
    <p v-if="error" :id="`${id}-erro`" class="text-danger">{{ error }}</p>
  </div>
</template>
