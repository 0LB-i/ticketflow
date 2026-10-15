<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Pessoa } from '@/components/editor/MentionList.vue'
import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'
import SelectField from '@/components/ui/SelectField.vue'
import TextAreaField from '@/components/ui/TextAreaField.vue'
import { useGrupos } from '@/composables/admin'
import { type Chamado, chamadosApi, useAcaoNoChamado, useStatus } from '@/composables/chamados'
import { formatarDataHora, formatarDuracao } from '@/composables/formato'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

import AttachmentList from './AttachmentList.vue'
import ClientPicker from './ClientPicker.vue'
import DeliverTicket from './DeliverTicket.vue'

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
const atribuir = useAcaoNoChamado(numero, (assignee: string) =>
  chamadosApi.atribuir(numero(), assignee),
)
// Vários responsáveis ou o grupo inteiro: cada mudança envia a lista completa.
const TODOS = 'todos'
const responsaveis = computed(() => [props.chamado.assignee, ...props.chamado.co_assignees])
const membrosDoGrupo = computed(() =>
  (grupos.data.value?.find((g) => g.id === props.chamado.team.id)?.members ?? []).filter(
    (m) => m.is_active,
  ),
)
const membros = computed(() => {
  const fora = membrosDoGrupo.value.filter(
    (m) => !responsaveis.value.some((r) => r.id === m.user_id),
  )
  if (!fora.length) return []
  return [
    { value: TODOS, label: t('novoChamado.todosDoGrupo') },
    ...fora.map((m) => ({ value: m.user_id, label: m.display_name })),
  ]
})
const definirResponsaveis = useAcaoNoChamado(numero, (ids: string[]) =>
  chamadosApi.definirResponsaveis(numero(), ids),
)
function mudarResponsaveis(ids: string[]) {
  executar(() => definirResponsaveis.mutateAsync(ids), t('chamado.feito.atribuido'))
}
const outroResponsavel = ref('')
watch(outroResponsavel, (id) => {
  if (!id) return
  outroResponsavel.value = ''
  const novos = id === TODOS ? membrosDoGrupo.value.map((m) => m.user_id) : [id]
  mudarResponsaveis([...new Set([...responsaveis.value.map((r) => r.id), ...novos])])
})

// --- status ---
// Qualquer status (set_status); os concluídos só com set_status_closed (em revisão, só o
// supervisor ou o admin).
const statusLista = useStatus()
const opcoesStatus = computed(() =>
  (statusLista.data.value ?? [])
    .filter(
      (s) =>
        s.kind !== 'closed' ||
        s.id === props.chamado.status.id ||
        pode.value.has('set_status_closed'),
    )
    .map((s) => ({ value: String(s.id), label: s.name })),
)
const trocarStatus = useAcaoNoChamado(numero, (id: number) =>
  chamadosApi.mudarStatusPara(numero(), id),
)
const statusAtual = computed({
  get: () => String(props.chamado.status.id),
  set: (id: string) => {
    if (id && id !== String(props.chamado.status.id))
      executar(() => trocarStatus.mutateAsync(Number(id)), t('chamado.feito.status'))
  },
})

// --- cliente: obrigatório, troca mas não sai ---
const trocarCliente = useAcaoNoChamado(numero, (id: string) =>
  chamadosApi.trocarCliente(numero(), id),
)
const cliente = computed({
  get: () => props.chamado.client ?? null,
  set: (c: { id: string; name: string } | null) => {
    if (c && c.id !== props.chamado.client?.id)
      executar(() => trocarCliente.mutateAsync(c.id), t('chamado.feito.cliente'))
  },
})

// --- cancelamento: só a confirmação, sem motivo ---
const cancelando = ref(false)
const cancelar = useAcaoNoChamado(numero, () =>
  chamadosApi.mudarStatus(numero(), { action: 'cancel', attachment_ids: [] }),
)
async function confirmarCancelamento() {
  cancelando.value = false
  await executar(() => cancelar.mutateAsync(undefined), t('chamado.feito.cancel'))
}

// --- transferência: vai para o outro grupo com um responsável de lá ---
const transferindo = ref(false)
const destino = ref('')
const novoResponsavel = ref('')
const motivo = ref('')
const outrosGrupos = computed(() =>
  (grupos.data.value ?? [])
    .filter((g) => g.is_active && g.id !== props.chamado.team.id)
    .map((g) => ({ value: g.id, label: g.name })),
)
const membrosDoDestino = computed(() =>
  (grupos.data.value?.find((g) => g.id === destino.value)?.members ?? [])
    .filter((m) => m.is_active)
    .map((m) => ({ value: m.user_id, label: m.display_name })),
)
watch(destino, () => (novoResponsavel.value = ''))
const transferir = useAcaoNoChamado(
  numero,
  (body: { team_id: string; assignee_id: string; reason: string }) =>
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
    () =>
      transferir.mutateAsync({
        team_id: destino.value,
        assignee_id: novoResponsavel.value,
        reason: motivo.value,
      }),
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
</script>

<template>
  <aside
    class="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4"
    :aria-label="t('chamado.dados')"
  >
    <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>

    <ClientPicker
      v-if="pode.has('edit')"
      v-model="cliente"
      :label="t('chamado.cliente')"
      obrigatorio
    />

    <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
      <template v-if="chamado.client && !pode.has('edit')">
        <dt class="text-muted">{{ t('chamado.cliente') }}</dt>
        <dd class="font-medium">{{ chamado.client.name }}</dd>
      </template>
      <template v-if="chamado.beneficiary_name">
        <dt class="text-muted">{{ t('chamado.contato') }}</dt>
        <dd>{{ chamado.beneficiary_name }}</dd>
      </template>
      <dt class="text-muted">{{ t('chamado.grupo') }}</dt>
      <dd class="font-medium">{{ chamado.team.name }}</dd>
      <template v-if="!pode.has('assign_others')">
        <dt class="text-muted">{{ t('chamado.responsavel') }}</dt>
        <dd class="font-medium">
          {{ responsaveis.map((u) => u.display_name).join(', ') }}
        </dd>
      </template>
      <dt class="text-muted">{{ t('chamado.tipo') }}</dt>
      <dd>{{ t(`tipos.${chamado.type}`) }}</dd>
      <dt class="text-muted">{{ t('chamado.inicio') }}</dt>
      <dd class="tabular-nums">{{ formatarDataHora(chamado.started_at) }}</dd>
      <template v-if="chamado.resolution_code">
        <dt class="text-muted">{{ t('chamado.resolucao') }}</dt>
        <dd>{{ chamado.resolution_code.name }} · {{ formatarDataHora(chamado.closed_at) }}</dd>
      </template>
    </dl>

    <SelectField
      v-if="pode.has('set_status')"
      v-model="statusAtual"
      :label="t('chamados.status')"
      :options="opcoesStatus"
    />

    <div class="flex flex-wrap gap-2">
      <Button
        v-if="pode.has('assign_self')"
        size="sm"
        :disabled="atribuir.isPending.value"
        @click="executar(() => atribuir.mutateAsync('me'), t('chamado.feito.assumido'))"
      >
        {{ t('chamado.assumir') }}
      </Button>
      <Button v-if="pode.has('transfer')" size="sm" variant="secondary" @click="abrirTransferencia">
        {{ t('chamado.transferir') }}
      </Button>
      <Button v-if="pode.has('cancel')" size="sm" variant="danger" @click="cancelando = true">
        {{ t('chamado.acoes.cancel') }}
      </Button>
    </div>
    <div v-if="pode.has('assign_others')" class="flex flex-col gap-2">
      <SelectField
        v-model="outroResponsavel"
        :label="t('chamado.atribuirA')"
        :placeholder="t('novoChamado.adicionarUsuario')"
        :options="membros"
      />
      <ul class="flex flex-wrap gap-2" :aria-label="t('chamado.responsavel')">
        <li
          v-for="r in responsaveis"
          :key="r.id"
          class="inline-flex items-center gap-1 rounded-full bg-surface-raised py-0.5 pr-1 pl-3"
        >
          {{ r.display_name }}
          <button
            v-if="responsaveis.length > 1"
            type="button"
            class="rounded-full p-0.5 text-muted hover:bg-border"
            :aria-label="t('novoChamado.removerUsuario', { nome: r.display_name })"
            :disabled="definirResponsaveis.isPending.value"
            @click="mudarResponsaveis(responsaveis.filter((o) => o.id !== r.id).map((o) => o.id))"
          >
            <X class="size-4" aria-hidden="true" />
          </button>
        </li>
      </ul>
    </div>

    <section class="flex flex-col gap-2 border-t border-border pt-4" aria-labelledby="tempo-titulo">
      <div class="flex items-baseline justify-between gap-2">
        <h2 id="tempo-titulo" class="font-semibold">{{ t('chamado.tempoGasto') }}</h2>
        <p v-if="chamado.time_spent_minutes" class="text-lg font-semibold tabular-nums">
          <span class="sr-only">{{ t('chamado.tempoTotal') }}:</span>
          {{ formatarDuracao(chamado.time_spent_minutes) }}
        </p>
      </div>
      <p v-if="!chamado.time_by_person.length" class="text-muted">{{ t('chamado.semTempo') }}</p>
      <dl v-else class="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1">
        <template v-for="p in chamado.time_by_person" :key="p.id">
          <dt>{{ p.display_name }}</dt>
          <dd class="text-right tabular-nums">{{ formatarDuracao(p.minutes) }}</dd>
        </template>
      </dl>
    </section>

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
          {{ w.display_name }}
          <button
            v-if="podeRemover(w.id)"
            type="button"
            class="rounded-full p-0.5 text-muted hover:bg-border"
            :aria-label="t('chamado.removerObservador', { nome: w.display_name })"
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

    <section
      v-if="chamado.attachments.length"
      class="flex flex-col gap-2 border-t border-border pt-4"
      aria-labelledby="anexos-titulo"
    >
      <h2 id="anexos-titulo" class="font-semibold">
        {{ t('anexos.tituloComTotal', { n: chamado.attachments.length }) }}
      </h2>
      <AttachmentList :anexos="chamado.attachments" />
    </section>
    <DeliverTicket v-if="pode.has('set_status')" :chamado="chamado" />

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
        <SelectField
          v-model="novoResponsavel"
          :label="t('chamado.novoResponsavel')"
          :placeholder="t('chamado.escolhaMembro')"
          :options="membrosDoDestino"
          required
        />
        <TextAreaField v-model="motivo" :label="t('chamado.motivo')" required />
      </div>
      <template #actions>
        <Button variant="secondary" @click="transferindo = false">{{ t('comum.cancelar') }}</Button>
        <Button
          :disabled="!destino || !novoResponsavel || !motivo.trim() || transferir.isPending.value"
          @click="confirmarTransferencia"
        >
          {{ t('chamado.transferir') }}
        </Button>
      </template>
    </Modal>

    <Modal
      v-model:open="cancelando"
      :title="t('chamado.cancelarTitulo')"
      :description="t('chamado.cancelarTexto')"
    >
      <template #actions>
        <Button variant="secondary" @click="cancelando = false">{{
          t('chamado.naoCancelar')
        }}</Button>
        <Button
          variant="danger"
          :disabled="cancelar.isPending.value"
          @click="confirmarCancelamento"
        >
          {{ t('chamado.acoes.cancel') }}
        </Button>
      </template>
    </Modal>
  </aside>
</template>
