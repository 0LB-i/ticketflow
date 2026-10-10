<script setup lang="ts">
import { ArrowDown, ArrowUp, Pencil, Trash2 } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Schemas } from '@/api/client'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'
import SelectField from '@/components/ui/SelectField.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import TextField from '@/components/ui/TextField.vue'
import { statusApi, useAlteracao } from '@/composables/admin'
import { useStatus } from '@/composables/chamados'
import { useToast } from '@/composables/useToast'

type Status = Schemas['StatusOut']
type Comportamento = Schemas['StatusCreate']['kind']

/**
 * Status dos chamados: criar, renomear, ordenar e remover. O comportamento (`kind`) é o que o
 * sistema entende do status e não muda depois de criado; a ordem é a das listas.
 */
const { t } = useI18n()
const toast = useToast()
const status = useStatus()
// A remoção move chamados de status: a lista de chamados também precisa ser relida.
const alterar = useAlteracao(async (fn: () => Promise<unknown>) => fn(), ['status', 'chamados'])
const erro = ref<string | null>(null)

const COMPORTAMENTOS: Comportamento[] = ['open', 'waiting', 'closed', 'canceled']
const opcoesComportamento = computed(() =>
  COMPORTAMENTOS.map((k) => ({ value: k, label: t(`statusConfig.comportamentos.${k}`) })),
)
const lista = computed(() => status.data.value ?? [])

async function executar(fn: () => Promise<unknown>, aviso: string) {
  erro.value = null
  try {
    await alterar.mutateAsync(fn)
    toast.show({ title: aviso })
    return true
  } catch (e) {
    erro.value = (e as Error).message
    return false
  }
}

// --- novo ---
const novoNome = ref('')
const novoComportamento = ref<Comportamento>('open')
async function criar() {
  if (!novoNome.value.trim()) return
  const ok = await executar(
    () => statusApi.criar({ name: novoNome.value, kind: novoComportamento.value }),
    t('statusConfig.criado'),
  )
  if (ok) novoNome.value = ''
}

// --- renomear ---
const renomeando = ref<number | null>(null)
const nome = ref('')
function abrirRenomear(s: Status) {
  renomeando.value = s.id
  nome.value = s.name
}
async function renomear(s: Status) {
  if (nome.value.trim() && nome.value.trim() !== s.name) {
    const ok = await executar(
      () => statusApi.renomear({ id: s.id, name: nome.value }),
      t('comum.salvo'),
    )
    if (!ok) return
  }
  renomeando.value = null
}

// --- ordenar ---
function mover(indice: number, passo: -1 | 1) {
  const ids = lista.value.map((s) => s.id)
  const [id] = ids.splice(indice, 1)
  ids.splice(indice + passo, 0, id!)
  executar(() => statusApi.ordenar(ids), t('statusConfig.ordemSalva'))
}

// --- remover ---
const removendo = ref<Status | null>(null)
const mesmoComportamento = (s: Status) =>
  lista.value.filter((o) => o.kind === s.kind && o.id !== s.id)
/** Para onde vão os chamados: o padrão do comportamento, ou o próximo, se o removido é o padrão. */
const destino = computed(() => {
  if (!removendo.value) return null
  const outros = mesmoComportamento(removendo.value)
  return outros.find((o) => o.is_default) ?? outros[0] ?? null
})
const contagem = (n: number) =>
  n === 0
    ? t('statusConfig.chamados0')
    : n === 1
      ? t('statusConfig.chamados1')
      : t('statusConfig.chamadosN', { n })
const avisoRemocao = computed(() => {
  const n = removendo.value?.ticket_count ?? 0
  if (n === 0) return t('statusConfig.removerSemChamados')
  const destinoNome = destino.value?.name
  return n === 1
    ? t('statusConfig.removerComUm', { destino: destinoNome })
    : t('statusConfig.removerComVarios', { n, destino: destinoNome })
})

async function remover() {
  const s = removendo.value!
  removendo.value = null
  await executar(() => statusApi.remover(s.id), t('statusConfig.removido', { nome: s.name }))
}
</script>

<template>
  <section
    class="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4 md:p-6"
    aria-labelledby="status-titulo"
  >
    <div>
      <h2 id="status-titulo" class="font-semibold">{{ t('statusConfig.titulo') }}</h2>
      <p class="mt-1 text-muted">{{ t('statusConfig.descricao') }}</p>
    </div>
    <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>

    <p v-if="status.isPending.value" class="text-muted">{{ t('comum.carregando') }}</p>
    <ul v-else class="flex flex-col divide-y divide-border rounded-md border border-border">
      <li v-for="(s, i) in lista" :key="s.id" class="flex flex-wrap items-center gap-3 px-3 py-2">
        <form
          v-if="renomeando === s.id"
          class="flex flex-1 flex-wrap items-end gap-2"
          @submit.prevent="renomear(s)"
        >
          <div class="min-w-48 flex-1">
            <TextField v-model="nome" :label="t('statusConfig.nome')" required />
          </div>
          <Button type="submit" size="sm" :disabled="alterar.isPending.value">
            {{ t('comum.salvar') }}
          </Button>
          <Button size="sm" variant="ghost" @click="renomeando = null">
            {{ t('comum.cancelar') }}
          </Button>
        </form>
        <template v-else>
          <div class="flex min-w-48 flex-1 flex-wrap items-center gap-2">
            <StatusBadge :kind="s.kind" :label="s.name" />
            <span class="text-muted">{{ t(`statusConfig.comportamentos.${s.kind}`) }}</span>
            <Badge v-if="s.is_default" color="gray">{{ t('statusConfig.padrao') }}</Badge>
          </div>
          <span class="text-muted tabular-nums">
            {{ contagem(s.ticket_count) }}
          </span>
          <div class="flex gap-1">
            <Button
              size="sm"
              variant="ghost"
              :disabled="i === 0 || alterar.isPending.value"
              :aria-label="t('statusConfig.subir', { nome: s.name })"
              :title="t('statusConfig.subir', { nome: s.name })"
              @click="mover(i, -1)"
            >
              <ArrowUp class="size-4" aria-hidden="true" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              :disabled="i === lista.length - 1 || alterar.isPending.value"
              :aria-label="t('statusConfig.descer', { nome: s.name })"
              :title="t('statusConfig.descer', { nome: s.name })"
              @click="mover(i, 1)"
            >
              <ArrowDown class="size-4" aria-hidden="true" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              :aria-label="t('statusConfig.renomear', { nome: s.name })"
              :title="t('statusConfig.renomear', { nome: s.name })"
              @click="abrirRenomear(s)"
            >
              <Pencil class="size-4" aria-hidden="true" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              :disabled="!mesmoComportamento(s).length"
              :aria-label="t('statusConfig.remover', { nome: s.name })"
              :title="
                mesmoComportamento(s).length
                  ? t('statusConfig.remover', { nome: s.name })
                  : t('statusConfig.unico')
              "
              @click="removendo = s"
            >
              <Trash2 class="size-4" aria-hidden="true" />
            </Button>
          </div>
        </template>
      </li>
    </ul>

    <form class="flex flex-wrap items-end gap-3" novalidate @submit.prevent="criar">
      <div class="min-w-48 flex-1">
        <TextField v-model="novoNome" :label="t('statusConfig.novo')" />
      </div>
      <div class="w-64">
        <SelectField
          v-model="novoComportamento"
          :label="t('statusConfig.comportamento')"
          :options="opcoesComportamento"
        />
      </div>
      <Button type="submit" :disabled="!novoNome.trim() || alterar.isPending.value">
        {{ t('comum.adicionar') }}
      </Button>
    </form>
    <p class="text-muted">{{ t(`statusConfig.explicacoes.${novoComportamento}`) }}</p>

    <Modal
      :open="removendo !== null"
      :title="t('statusConfig.removerTitulo', { nome: removendo?.name })"
      :description="avisoRemocao"
      @update:open="(v: boolean) => !v && (removendo = null)"
    >
      <template #actions>
        <Button variant="secondary" @click="removendo = null">{{ t('comum.cancelar') }}</Button>
        <Button variant="danger" @click="remover">{{ t('comum.remover') }}</Button>
      </template>
    </Modal>
  </section>
</template>
