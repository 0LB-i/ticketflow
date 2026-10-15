<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import RichEditor from '@/components/editor/RichEditor.vue'
import AttachmentUploader from '@/components/tickets/AttachmentUploader.vue'
import ClientPicker from '@/components/tickets/ClientPicker.vue'
import Button from '@/components/ui/Button.vue'
import DateTimeField from '@/components/ui/DateTimeField.vue'
import SelectField from '@/components/ui/SelectField.vue'
import TextField from '@/components/ui/TextField.vue'
import { useGrupos } from '@/composables/admin'
import { anexosNoTexto } from '@/composables/anexos'
import { chamadosApi, useAcaoNoChamado, usePessoas, useStatus } from '@/composables/chamados'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

/** Registro de chamado (docs/10 §10.4). */
useHead('novoChamado.titulo')
const { t } = useI18n()
const router = useRouter()
const toast = useToast()
const auth = useAuthStore()
const status = useStatus()
const grupos = useGrupos()
const pessoas = usePessoas()
const editor = useTemplateRef('editor')
const anexador = useTemplateRef('anexador')

const meusGrupos = computed(() => auth.me?.teams ?? [])
const form = reactive({
  team: meusGrupos.value.length === 1 ? meusGrupos.value[0]!.id : '',
  status: '',
  title: '',
  description: '',
  // Início do trabalho: nulo acompanha a hora atual até a pessoa mudar.
  inicio: null as string | null,
  cliente: null as { id: string; name: string } | null,
  contato: '',
  // Responsáveis: começa com quem registra; vazio deixa na fila do grupo.
  responsaveis: auth.me ? [auth.me.id] : ([] as string[]),
  observadores: [] as string[],
  anexos: [] as string[],
})
const erro = ref<string | null>(null)
const tentou = ref(false)

// Os grupos podem ter mudado depois do login (ex.: o admin incluiu a pessoa num grupo).
onMounted(() => auth.carregar())
watch(meusGrupos, (grupos) => {
  if (!form.team && grupos.length === 1) form.team = grupos[0]!.id
})

// Status: começa em Pendente (o primeiro do tipo "open") e pode ser qualquer um dos cinco.
const podeEscolherStatus = computed(() => auth.pode('ticket.transition'))
const opcoesStatus = computed(() =>
  (status.data.value ?? []).map((s) => ({ value: String(s.id), label: s.name })),
)
watch(
  () => status.data.value,
  (lista) => {
    if (!form.status && lista) form.status = String(lista.find((s) => s.kind === 'open')?.id ?? '')
  },
  { immediate: true },
)
watch(
  () => form.team,
  () => (form.responsaveis = auth.me ? [auth.me.id] : []),
)

const TODOS = 'todos'
const membrosDoGrupo = computed(() =>
  (grupos.data.value?.find((g) => g.id === form.team)?.members ?? []).filter((m) => m.is_active),
)
const nomesDosMembros = computed(
  () => new Map(membrosDoGrupo.value.map((m) => [m.user_id, m.display_name])),
)
const opcoesResponsavel = computed(() => {
  const fora = membrosDoGrupo.value.filter((m) => !form.responsaveis.includes(m.user_id))
  if (!fora.length) return []
  return [
    { value: TODOS, label: t('novoChamado.todosDoGrupo') },
    ...fora.map((m) => ({ value: m.user_id, label: m.display_name })),
  ]
})
const novoResponsavel = ref('')
watch(novoResponsavel, (id) => {
  if (!id) return
  form.responsaveis =
    id === TODOS ? membrosDoGrupo.value.map((m) => m.user_id) : [...form.responsaveis, id]
  novoResponsavel.value = ''
})
const nomes = computed(() => new Map(pessoas.value.map((p) => [p.id, p.label])))
const opcoesObservador = computed(() =>
  pessoas.value
    .filter((p) => p.id !== auth.me?.id && !form.observadores.includes(p.id))
    .map((p) => ({ value: p.id, label: p.label })),
)
const novoObservador = ref('')
watch(novoObservador, (id) => {
  if (id) {
    form.observadores.push(id)
    novoObservador.value = ''
  }
})

const faltando = computed(() => ({
  team: !form.team,
  title: form.title.trim().length < 3,
  // A API aceita até 5 minutos adiantado (relógio do computador); aqui, qualquer futuro.
  inicio: form.inicio !== null && new Date(form.inicio).getTime() > Date.now(),
}))

const registrar = useAcaoNoChamado('novo', chamadosApi.registrar)

async function enviar() {
  tentou.value = true
  erro.value = null
  if (Object.values(faltando.value).some(Boolean)) return
  // A API guarda um responsável principal (quem registra, se estiver na lista) e os demais.
  const eu = auth.me?.id
  const principal = eu && form.responsaveis.includes(eu) ? eu : form.responsaveis[0]
  try {
    const chamado = await registrar.mutateAsync({
      title: form.title,
      description: form.description,
      team_id: form.team,
      status_id: podeEscolherStatus.value && form.status ? Number(form.status) : null,
      started_at: form.inicio,
      client_id: form.cliente?.id ?? null,
      beneficiary_name: form.contato.trim() || null,
      assignee: principal === eu ? 'me' : (principal ?? null),
      co_assignee_ids: form.responsaveis.filter((id) => id !== principal),
      watcher_ids: form.observadores,
      mention_ids: editor.value?.mencionados() ?? [],
      attachment_ids: [...new Set([...form.anexos, ...anexosNoTexto(form.description)])],
    })
    toast.show({
      title: t('novoChamado.registrado', { numero: chamado.number }),
      description: chamado.title,
    })
    await router.push(`/chamados/${chamado.number}`)
  } catch (e) {
    erro.value = (e as Error).message
  }
}
</script>

<template>
  <!-- Pensada para computador: texto à esquerda e campos à direita, sem rolar a página. -->
  <div class="mx-auto flex max-w-7xl flex-col gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="text-xl font-semibold">{{ $t('novoChamado.titulo') }}</h1>
      <div v-if="meusGrupos.length" class="flex gap-2">
        <Button variant="secondary" @click="router.push('/chamados')">
          {{ $t('comum.cancelar') }}
        </Button>
        <Button
          type="submit"
          form="form-novo-chamado"
          :disabled="registrar.isPending.value || editor?.enviando || anexador?.enviando"
        >
          {{ $t('novoChamado.registrar') }}
        </Button>
      </div>
    </div>
    <p v-if="!meusGrupos.length" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">
      {{ $t('novoChamado.semGrupo') }}
    </p>

    <form
      v-else
      id="form-novo-chamado"
      class="flex flex-col gap-4"
      novalidate
      @submit.prevent="enviar"
    >
      <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>

      <div class="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div class="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4 md:p-6">
          <TextField
            v-model="form.title"
            :label="$t('novoChamado.tituloCampo')"
            :hint="$t('novoChamado.tituloDica')"
            :error="tentou && faltando.title ? $t('novoChamado.tituloCurto') : undefined"
            required
          />
          <RichEditor
            ref="editor"
            v-model="form.description"
            :label="$t('novoChamado.descricao')"
            :placeholder="$t('novoChamado.descricaoDica')"
            :pessoas="pessoas"
            alto
            anexar
          />
          <AttachmentUploader ref="anexador" v-model="form.anexos" />
        </div>

        <div class="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4">
          <DateTimeField
            v-model="form.inicio"
            :label="$t('chamado.inicio')"
            :error="tentou && faltando.inicio ? $t('novoChamado.inicioNoFuturo') : undefined"
          />
          <SelectField
            v-model="form.team"
            :label="$t('novoChamado.grupo')"
            :options="meusGrupos.map((g) => ({ value: g.id, label: g.name }))"
            :error="tentou && faltando.team ? $t('novoChamado.escolhaGrupo') : undefined"
            required
          />
          <div v-if="form.team" class="flex flex-col gap-2">
            <SelectField
              v-model="novoResponsavel"
              :label="$t('novoChamado.usuarios')"
              :placeholder="$t('novoChamado.adicionarUsuario')"
              :options="opcoesResponsavel"
            />
            <p v-if="!form.responsaveis.length" class="text-muted">
              {{ $t('novoChamado.usuariosDica') }}
            </p>
            <ul v-else class="flex flex-wrap gap-2">
              <li
                v-for="id in form.responsaveis"
                :key="id"
                class="inline-flex items-center gap-1 rounded-full bg-surface-raised py-0.5 pr-1 pl-3"
              >
                {{ nomesDosMembros.get(id) ?? nomes.get(id) }}
                <button
                  type="button"
                  class="rounded-full p-0.5 text-muted hover:bg-border"
                  :aria-label="
                    $t('novoChamado.removerUsuario', {
                      nome: nomesDosMembros.get(id) ?? nomes.get(id),
                    })
                  "
                  @click="form.responsaveis = form.responsaveis.filter((r) => r !== id)"
                >
                  <X class="size-4" aria-hidden="true" />
                </button>
              </li>
            </ul>
          </div>
          <SelectField
            v-if="podeEscolherStatus"
            v-model="form.status"
            :label="$t('chamados.status')"
            :options="opcoesStatus"
          />

          <div class="flex flex-col gap-4 border-t border-border pt-4">
            <ClientPicker v-model="form.cliente" :label="$t('chamado.cliente')" />
            <TextField
              v-model="form.contato"
              :label="$t('chamado.contato')"
              :hint="$t('chamado.contatoDica')"
            />
          </div>

          <div class="flex flex-col gap-2 border-t border-border pt-4">
            <SelectField
              v-model="novoObservador"
              :label="$t('chamado.observadores')"
              :placeholder="$t('chamado.adicionarColega')"
              :options="opcoesObservador"
            />
            <ul v-if="form.observadores.length" class="flex flex-wrap gap-2">
              <li
                v-for="id in form.observadores"
                :key="id"
                class="inline-flex items-center gap-1 rounded-full bg-surface-raised py-0.5 pr-1 pl-3"
              >
                {{ nomes.get(id) }}
                <button
                  type="button"
                  class="rounded-full p-0.5 text-muted hover:bg-border"
                  :aria-label="$t('chamado.removerObservador', { nome: nomes.get(id) })"
                  @click="form.observadores = form.observadores.filter((o) => o !== id)"
                >
                  <X class="size-4" aria-hidden="true" />
                </button>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </form>
  </div>
</template>
