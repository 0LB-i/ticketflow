<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Pessoa } from '@/components/editor/MentionList.vue'
import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'
import PriorityBadge, { type Prioridade } from '@/components/ui/PriorityBadge.vue'
import SelectField from '@/components/ui/SelectField.vue'
import TextAreaField from '@/components/ui/TextAreaField.vue'
import { useGrupos } from '@/composables/admin'
import { type Chamado, chamadosApi, useAcaoNoChamado } from '@/composables/chamados'
import { formatarDataHora } from '@/composables/formato'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

import TicketEditPanel from './TicketEditPanel.vue'

/** Dados do chamado e as ações sobre eles, conforme `allowed_actions` (docs/08 §8.5). */
const props = defineProps<{ chamado: Chamado; pessoas: Pessoa[] }>()
const { t } = useI18n()
const toast = useToast()
const auth = useAuthStore()
const grupos = useGrupos()

const numero = () => String(props.chamado.number)
const pode = computed(() => new Set(props.chamado.allowed_actions))
const erro = ref<string | null>(null)

async function executar(fn: () => Promise<unknown>, aviso: string) {
  erro.value = null
  try {
    await fn()
    toast.show({ title: aviso })
  } catch (e) {
    erro.value = (e as Error).message
  }
}

// --- responsável ---
const atribuir = useAcaoNoChamado(numero, (assignee: string | null) =>
  chamadosApi.atribuir(numero(), assignee),
)
const outroResponsavel = ref('')
const membros = computed(() =>
  (grupos.data.value?.find((g) => g.id === props.chamado.team.id)?.members ?? [])
    .filter((m) => m.is_active && m.user_id !== props.chamado.assignee?.id)
    .map((m) => ({ value: m.user_id, label: m.full_name })),
)
watch(outroResponsavel, (id) => {
  if (!id) return
  outroResponsavel.value = ''
  executar(() => atribuir.mutateAsync(id), t('chamado.feito.atribuido'))
})

// --- transferência ---
const transferindo = ref(false)
const destino = ref('')
const motivo = ref('')
const outrosGrupos = computed(() =>
  (grupos.data.value ?? [])
    .filter((g) => g.is_active && g.id !== props.chamado.team.id)
    .map((g) => ({ value: g.id, label: g.name })),
)
const transferir = useAcaoNoChamado(numero, (body: { team_id: string; reason: string }) =>
  chamadosApi.transferir(numero(), body),
)
function abrirTransferencia() {
  destino.value = ''
  motivo.value = ''
  transferindo.value = true
}
async function confirmarTransferencia() {
  transferindo.value = false
  await executar(
    () => transferir.mutateAsync({ team_id: destino.value, reason: motivo.value }),
    t('chamado.feito.transferido'),
  )
}

// --- observadores ---
const observar = useAcaoNoChamado(numero, (a: { usuario: string; observar: boolean }) =>
  chamadosApi.observar(numero(), a.usuario, a.observar),
)
const acompanho = computed(() => props.chamado.watchers.some((w) => w.id === auth.me?.id))
const novoObservador = ref('')
const candidatos = computed(() =>
  props.pessoas
    .filter((p) => !props.chamado.watchers.some((w) => w.id === p.id))
    .map((p) => ({ value: p.id, label: p.label })),
)
watch(novoObservador, (id) => {
  if (!id) return
  novoObservador.value = ''
  executar(
    () => observar.mutateAsync({ usuario: id, observar: true }),
    t('chamado.feito.observador'),
  )
})
const podeRemover = (id: string) =>
  pode.value.has('manage_watchers') || (id === auth.me?.id && pode.value.has('watch_self'))

const editando = ref(false)
</script>

<template>
  <aside
    class="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4"
    :aria-label="t('chamado.dados')"
  >
    <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>

    <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
      <template v-if="chamado.client">
        <dt class="text-muted">{{ t('chamado.cliente') }}</dt>
        <dd class="font-medium">{{ chamado.client.name }}</dd>
      </template>
      <template v-if="chamado.beneficiary_name">
        <dt class="text-muted">{{ t('chamado.contato') }}</dt>
        <dd>{{ chamado.beneficiary_name }}</dd>
      </template>
      <dt class="text-muted">{{ t('chamado.grupo') }}</dt>
      <dd class="font-medium">{{ chamado.team.name }}</dd>
      <dt class="text-muted">{{ t('chamado.responsavel') }}</dt>
      <dd class="font-medium">{{ chamado.assignee?.full_name ?? t('chamado.naFila') }}</dd>
      <dt class="text-muted">{{ t('chamado.tipo') }}</dt>
      <dd>{{ t(`tipos.${chamado.type}`) }}</dd>
      <dt class="text-muted">{{ t('chamado.inicio') }}</dt>
      <dd class="tabular-nums">{{ formatarDataHora(chamado.started_at) }}</dd>
      <dt class="text-muted">{{ t('chamado.prioridade') }}</dt>
      <dd class="flex flex-col items-start gap-1">
        <PriorityBadge :priority="chamado.priority as Prioridade" />
        <span v-if="chamado.priority_overridden" class="text-muted">{{
          t('chamado.forcada')
        }}</span>
      </dd>
      <template v-if="chamado.resolution_code">
        <dt class="text-muted">{{ t('chamado.resolucao') }}</dt>
        <dd>{{ chamado.resolution_code.name }} · {{ formatarDataHora(chamado.closed_at) }}</dd>
      </template>
      <template v-if="chamado.reopened_count">
        <dt class="text-muted">{{ t('chamado.reaberturas') }}</dt>
        <dd class="tabular-nums">{{ chamado.reopened_count }}</dd>
      </template>
    </dl>

    <div class="flex flex-wrap gap-2">
      <Button
        v-if="pode.has('assign_self')"
        size="sm"
        :disabled="atribuir.isPending.value"
        @click="executar(() => atribuir.mutateAsync('me'), t('chamado.feito.assumido'))"
      >
        {{ t('chamado.assumir') }}
      </Button>
      <Button
        v-if="pode.has('unassign')"
        size="sm"
        variant="secondary"
        :disabled="atribuir.isPending.value"
        @click="executar(() => atribuir.mutateAsync(null), t('chamado.feito.devolvido'))"
      >
        {{ t('chamado.devolver') }}
      </Button>
      <Button v-if="pode.has('transfer')" size="sm" variant="secondary" @click="abrirTransferencia">
        {{ t('chamado.transferir') }}
      </Button>
      <Button
        v-if="pode.has('edit') || pode.has('set_priority') || pode.has('set_status')"
        size="sm"
        variant="secondary"
        @click="editando = true"
      >
        {{ t('chamado.editar') }}
      </Button>
    </div>
    <SelectField
      v-if="pode.has('assign_others')"
      v-model="outroResponsavel"
      :label="t('chamado.atribuirA')"
      :placeholder="t('chamado.escolhaMembro')"
      :options="membros"
    />

    <section
      class="flex flex-col gap-2 border-t border-border pt-4"
      aria-labelledby="observadores-titulo"
    >
      <div class="flex items-center justify-between gap-2">
        <h2 id="observadores-titulo" class="font-semibold">{{ t('chamado.observadores') }}</h2>
        <Button
          v-if="pode.has('watch_self')"
          size="sm"
          variant="ghost"
          :disabled="observar.isPending.value"
          @click="
            executar(
              () => observar.mutateAsync({ usuario: auth.me!.id, observar: !acompanho }),
              t(acompanho ? 'chamado.feito.deixouDeAcompanhar' : 'chamado.feito.acompanhando'),
            )
          "
        >
          {{ acompanho ? t('chamado.deixarDeAcompanhar') : t('chamado.acompanhar') }}
        </Button>
      </div>
      <p v-if="!chamado.watchers.length" class="text-muted">{{ t('chamado.semObservadores') }}</p>
      <ul v-else class="flex flex-wrap gap-2">
        <li
          v-for="w in chamado.watchers"
          :key="w.id"
          class="inline-flex items-center gap-1 rounded-full bg-surface-raised py-0.5 pr-1 pl-3"
        >
          {{ w.full_name }}
          <button
            v-if="podeRemover(w.id)"
            type="button"
            class="rounded-full p-0.5 text-muted hover:bg-border"
            :aria-label="t('chamado.removerObservador', { nome: w.full_name })"
            @click="
              executar(
                () => observar.mutateAsync({ usuario: w.id, observar: false }),
                t('chamado.feito.observadorRemovido'),
              )
            "
          >
            <X class="size-4" aria-hidden="true" />
          </button>
        </li>
      </ul>
      <SelectField
        v-if="pode.has('manage_watchers')"
        v-model="novoObservador"
        :label="t('chamado.adicionarObservador')"
        :placeholder="t('chamado.adicionarColega')"
        :options="candidatos"
      />
    </section>

    <Modal
      v-model:open="transferindo"
      :title="t('chamado.transferirTitulo')"
      :description="t('chamado.transferirTexto')"
    >
      <div class="flex flex-col gap-4">
        <SelectField
          v-model="destino"
          :label="t('chamado.grupoDestino')"
          :options="outrosGrupos"
          required
        />
        <TextAreaField v-model="motivo" :label="t('chamado.motivo')" required />
      </div>
      <template #actions>
        <Button variant="secondary" @click="transferindo = false">{{ t('comum.cancelar') }}</Button>
        <Button
          :disabled="!destino || !motivo.trim() || transferir.isPending.value"
          @click="confirmarTransferencia"
        >
          {{ t('chamado.transferir') }}
        </Button>
      </template>
    </Modal>
    <TicketEditPanel v-model:open="editando" :chamado="chamado" />
  </aside>
</template>
