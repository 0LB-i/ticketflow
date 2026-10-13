<script setup lang="ts">
import { ChevronDown, X } from 'lucide-vue-next'
import {
  ComboboxAnchor,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxPortal,
  ComboboxRoot,
  ComboboxTrigger,
  ComboboxViewport,
} from 'reka-ui'
import { computed, ref, useId, watch } from 'vue'

import { useClientes } from '@/composables/clientes'
import { formatarDocumento } from '@/composables/documentos'

/** Cliente do chamado, opcional: busca na API por nome, nome fantasia ou CPF/CNPJ. */
defineProps<{ label: string }>()
const model = defineModel<{ id: string; name: string } | null>({ default: null })
const id = useId()

const aberto = ref(false)
const busca = ref('')
const termo = ref('')
let espera: ReturnType<typeof setTimeout> | undefined
watch(busca, (valor) => {
  clearTimeout(espera)
  espera = setTimeout(() => (termo.value = valor), 300)
})
// Só consulta a API com a lista aberta.
const clientes = useClientes(
  () => ({ q: termo.value, inativos: false }),
  () => aberto.value,
)
const opcoes = computed(() => clientes.data.value?.items ?? [])
</script>

<template>
  <div class="flex flex-col gap-1">
    <label :for="id" class="font-medium">{{ label }}</label>
    <ComboboxRoot v-model="model" v-model:open="aberto" by="id" ignore-filter open-on-click>
      <ComboboxAnchor
        class="inline-flex h-10 items-center gap-1 rounded-md border border-border-input bg-surface pr-1 pl-3"
      >
        <ComboboxInput
          :id="id"
          v-model="busca"
          :display-value="(c) => c?.name ?? ''"
          :placeholder="$t('chamado.buscarCliente')"
          class="h-full min-w-0 flex-1 bg-transparent text-fg outline-none placeholder:text-muted"
        />
        <button
          v-if="model"
          type="button"
          class="rounded p-1 text-muted hover:bg-surface-raised"
          :aria-label="$t('chamado.tirarCliente')"
          @click="model = null"
        >
          <X class="size-4" aria-hidden="true" />
        </button>
        <ComboboxTrigger class="rounded p-1 text-muted" :aria-label="label">
          <ChevronDown class="size-4" aria-hidden="true" />
        </ComboboxTrigger>
      </ComboboxAnchor>
      <ComboboxPortal>
        <ComboboxContent
          position="popper"
          :side-offset="4"
          class="z-50 max-h-(--reka-combobox-content-available-height) w-(--reka-combobox-trigger-width) overflow-y-auto rounded-md border border-border bg-surface p-1 text-fg shadow-lg"
        >
          <ComboboxViewport>
            <ComboboxEmpty class="px-2 py-1.5 text-muted">
              {{ clientes.isFetching.value ? $t('comum.carregando') : $t('chamado.nenhumCliente') }}
            </ComboboxEmpty>
            <ComboboxItem
              v-for="c in opcoes"
              :key="c.id"
              :value="{ id: c.id, name: c.name }"
              class="flex cursor-default flex-col rounded px-2 py-1.5 outline-none select-none data-highlighted:bg-surface-raised"
            >
              <span>{{ c.name }}</span>
              <span class="text-muted tabular-nums">
                {{ formatarDocumento(c.document, c.kind) }}
                <template v-if="c.trade_name"> · {{ c.trade_name }}</template>
              </span>
            </ComboboxItem>
          </ComboboxViewport>
        </ComboboxContent>
      </ComboboxPortal>
    </ComboboxRoot>
  </div>
</template>
