<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, ou } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Checkbox from '@/components/ui/Checkbox.vue'
import TextField from '@/components/ui/TextField.vue'
import { useAlteracao } from '@/composables/admin'
import { type Expediente, useExpediente } from '@/composables/relatorios'
import { useToast } from '@/composables/useToast'
import { idiomaAtual } from '@/i18n'

/**
 * Expediente (Configurações): dias, horário e feriados. O tempo de tarefa fora dele aparece como
 * hora extra nos relatórios.
 */
const { t } = useI18n()
const toast = useToast()
const atual = useExpediente()
const salvar = useAlteracao(
  async (body: Expediente) => ou(await api.PUT('/api/v1/admin/settings/work-hours', { body })),
  ['expediente', 'relatorios'],
)

const DIAS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'dom'] as const
const dias = ref<boolean[]>(DIAS.map(() => false))
const inicio = ref('')
const fim = ref('')
const feriados = ref<string[]>([])
const novoFeriado = ref('')
const erro = ref<string | null>(null)

watch(
  () => atual.data.value,
  (e) => {
    if (!e) return
    dias.value = DIAS.map((_, i) => e.weekdays.includes(i))
    inicio.value = e.start.slice(0, 5)
    fim.value = e.end.slice(0, 5)
    feriados.value = [...e.holidays]
  },
  { immediate: true },
)

const horarioValido = computed(() => Boolean(inicio.value && fim.value && fim.value > inicio.value))

function adicionarFeriado() {
  if (novoFeriado.value && !feriados.value.includes(novoFeriado.value)) {
    feriados.value = [...feriados.value, novoFeriado.value].sort()
  }
  novoFeriado.value = ''
}

const formatoData = computed(() => new Intl.DateTimeFormat(idiomaAtual(), { timeZone: 'UTC' }))
const dataLegivel = (iso: string) => formatoData.value.format(new Date(`${iso}T00:00:00Z`))

async function enviar() {
  erro.value = null
  try {
    await salvar.mutateAsync({
      weekdays: dias.value.flatMap((marcado, i) => (marcado ? [i] : [])),
      start: inicio.value,
      end: fim.value,
      holidays: feriados.value,
    })
    toast.show({ title: t('comum.salvo') })
  } catch (e) {
    erro.value = (e as Error).message
  }
}
</script>

<template>
  <form
    class="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4 md:p-6"
    aria-labelledby="expediente-titulo"
    novalidate
    @submit.prevent="enviar"
  >
    <div>
      <h2 id="expediente-titulo" class="font-semibold">{{ t('expediente.titulo') }}</h2>
      <p class="mt-1 text-muted">{{ t('expediente.descricao') }}</p>
    </div>
    <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>

    <fieldset class="flex flex-col gap-2">
      <legend class="pb-2 font-medium">{{ t('expediente.dias') }}</legend>
      <div class="flex flex-wrap gap-4">
        <Checkbox
          v-for="(d, i) in DIAS"
          :key="d"
          v-model="dias[i]"
          :label="t(`expediente.diasCurtos.${d}`)"
        />
      </div>
    </fieldset>

    <div class="grid max-w-md gap-4 sm:grid-cols-2">
      <TextField v-model="inicio" type="time" :label="t('expediente.inicio')" />
      <TextField
        v-model="fim"
        type="time"
        :label="t('expediente.fim')"
        :error="horarioValido ? undefined : t('expediente.horarioInvalido')"
      />
    </div>

    <div class="flex flex-col gap-2">
      <p class="font-medium">{{ t('expediente.feriados') }}</p>
      <p class="text-muted">{{ t('expediente.feriadosDica') }}</p>
      <ul v-if="feriados.length" class="flex flex-wrap gap-2">
        <li
          v-for="f in feriados"
          :key="f"
          class="inline-flex items-center gap-1 rounded-full bg-surface-raised py-1 pr-1 pl-3"
        >
          {{ dataLegivel(f) }}
          <button
            type="button"
            class="rounded-full p-1 text-muted hover:text-fg"
            :aria-label="t('expediente.removerFeriado', { data: dataLegivel(f) })"
            @click="feriados = feriados.filter((x) => x !== f)"
          >
            <X class="size-4" aria-hidden="true" />
          </button>
        </li>
      </ul>
      <div class="flex max-w-md items-end gap-2">
        <TextField v-model="novoFeriado" type="date" :label="t('expediente.novoFeriado')" />
        <Button variant="secondary" :disabled="!novoFeriado" @click="adicionarFeriado">
          {{ t('comum.adicionar') }}
        </Button>
      </div>
    </div>

    <div class="flex justify-end border-t border-border pt-4">
      <Button type="submit" :disabled="salvar.isPending.value || !horarioValido">
        {{ t('expediente.salvar') }}
      </Button>
    </div>
  </form>
</template>
