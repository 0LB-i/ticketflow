<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId } from 'vue'

import Button from '@/components/ui/Button.vue'
import { dataEHora, instante } from '@/composables/formato'

/**
 * Data e hora no fuso da empresa, em dois campos simples. `null` é "agora": mostra a hora atual,
 * que vai andando até a pessoa mudar a data ou a hora. O botão Agora volta a acompanhar.
 */
const props = defineProps<{ label: string; error?: string }>()
const model = defineModel<string | null>({ default: null })
const id = useId()

const agora = ref(new Date())
const relogio = setInterval(() => (agora.value = new Date()), 10_000)
onBeforeUnmount(() => clearInterval(relogio))

const valor = computed(() => dataEHora(model.value ? new Date(model.value) : agora.value))
const hoje = computed(() => dataEHora(agora.value).data)

function mudar(campo: 'data' | 'hora', evento: Event) {
  const digitado = (evento.target as HTMLInputElement).value
  if (!digitado) return
  const novo = { ...valor.value, [campo]: digitado }
  model.value = instante(novo.data, novo.hora).toISOString()
}

const classeInput = computed(() => [
  'h-10 rounded-md border bg-surface px-3 text-fg tabular-nums',
  props.error ? 'border-danger' : 'border-border-input',
])
</script>

<template>
  <fieldset
    class="flex flex-col gap-1"
    :aria-describedby="model === null ? undefined : `${id}-dica`"
  >
    <legend class="mb-1 font-medium">{{ label }}</legend>
    <div class="flex flex-wrap items-center gap-2">
      <input
        type="date"
        :value="valor.data"
        :max="hoje"
        :aria-label="$t('dataHora.data')"
        :aria-invalid="error ? true : undefined"
        :class="classeInput"
        @input="mudar('data', $event)"
      />
      <input
        type="time"
        :value="valor.hora"
        :aria-label="$t('dataHora.hora')"
        :aria-invalid="error ? true : undefined"
        :class="[classeInput, 'w-28']"
        @input="mudar('hora', $event)"
      />
      <Button size="sm" variant="secondary" :disabled="model === null" @click="model = null">
        {{ $t('dataHora.agora') }}
      </Button>
    </div>
    <p v-if="model !== null" :id="`${id}-dica`" class="text-muted">
      {{ $t('dataHora.ajustado') }}
    </p>
    <p v-if="error" class="text-danger">{{ error }}</p>
  </fieldset>
</template>
