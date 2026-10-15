<script setup lang="ts">
import { MessageCircle, Pencil } from 'lucide-vue-next'
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { type LocationQueryRaw, useRoute, useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Checkbox from '@/components/ui/Checkbox.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SelectField from '@/components/ui/SelectField.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useGrupos } from '@/composables/admin'
import {
  type Fila,
  type FiltroChamados,
  useChamados,
  useContagens,
  useStatus,
  useStatusEmMassa,
} from '@/composables/chamados'
import { formatarDataHora, formatarDuracao, formatarHaQuanto } from '@/composables/formato'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

/**
 * Filas (docs/10 §10.6, docs/13 §13.5): uma aba por fila, na ordenação padrão (o mais antigo
 * primeiro). A aba e os filtros ficam na URL, para o link poder ser compartilhado.
 */
useHead('chamados.titulo')
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const toast = useToast()
const auth = useAuthStore()
const grupos = useGrupos()
const contagens = useContagens()
// Os grupos da pessoa (aba inicial, seleção em massa) podem ter mudado depois do login.
onMounted(() => auth.carregar())

const ABAS: { slug: string; fila: Fila }[] = [
  { slug: 'meus', fila: 'mine' },
  { slug: 'aguardando', fila: 'waiting' },
  { slug: 'acompanhando', fila: 'watching' },
  { slug: 'todos', fila: 'all' },
]
// Opção "todos" dos filtros (não vai para a URL).
const TODOS = '*'
const KINDS = ['open', 'waiting', 'delivered', 'closed', 'canceled'] as const
const RESPONSAVEL = { eu: 'me' } as const

const texto = (chave: string) => {
  const valor = route.query[chave]
  return typeof valor === 'string' && valor ? valor : null
}
// Quem não está em nenhum grupo (admin, auditor) não tem filas: começa em Todos.
const abaPadrao = computed(() => (auth.me?.teams.length ? 'meus' : 'todos'))
const aba = computed(
  () => ABAS.find((a) => a.slug === texto('aba')) ?? ABAS.find((a) => a.slug === abaPadrao.value)!,
)
const emTodos = computed(() => aba.value.fila === 'all')

const filtro = computed<FiltroChamados>(() => {
  const status = texto('status')
  const responsavel = texto('responsavel')
  return {
    view: aba.value.fila,
    team: texto('grupo'),
    q: texto('q'),
    // Status e responsável só filtram a aba Todos; as outras já os definem.
    status:
      emTodos.value && KINDS.some((k) => k === status) ? [status as (typeof KINDS)[number]] : null,
    assignee:
      emTodos.value && responsavel && responsavel in RESPONSAVEL
        ? RESPONSAVEL[responsavel as keyof typeof RESPONSAVEL]
        : null,
  }
})
const chamados = useChamados(filtro)
const linhas = computed(() => chamados.data.value?.pages.flatMap((p) => p.items) ?? [])

/** Muda um parâmetro da URL; a opção "todos" (ou nulo) tira o filtro. */
function filtrar(chave: string, valor: string | null) {
  const query: LocationQueryRaw = { ...route.query, [chave]: valor }
  if (valor === null || valor === TODOS) delete query[chave]
  // Status e responsável só existem na aba Todos.
  if (chave === 'aba' && valor !== 'todos') {
    delete query.status
    delete query.responsavel
  }
  router.replace({ query })
}
const modelo = (chave: string) =>
  computed({
    get: () => texto(chave) ?? TODOS,
    set: (valor: string) => filtrar(chave, valor),
  })
const grupo = modelo('grupo')
const status = modelo('status')
const responsavel = modelo('responsavel')

const opcoesGrupo = computed(() => [
  { value: TODOS, label: t('chamados.filtros.todosOsGrupos') },
  ...(grupos.data.value ?? [])
    .filter((g) => g.is_active)
    .map((g) => ({ value: g.id, label: g.name })),
])
const opcoesStatus = computed(() => [
  { value: TODOS, label: t('chamados.filtros.todos') },
  ...KINDS.map((k) => ({ value: k, label: t(`chamados.filtros.kinds.${k}`) })),
])
const opcoesResponsavel = computed(() => [
  { value: TODOS, label: t('chamados.filtros.todos') },
  { value: 'eu', label: t('chamados.filtros.eu') },
])

const contagem = (fila: Fila) => (fila === 'all' ? null : (contagens.data.value?.[fila] ?? null))

const colunas = computed(() => [
  ...(podeEmMassa.value
    ? [{ key: 'sel', label: t('chamados.selecionarTodos'), class: 'w-px' }]
    : []),
  { key: 'number', label: t('chamados.numero') },
  { key: 'title', label: t('chamados.tituloColuna') },
  { key: 'client', label: t('chamado.cliente'), class: 'hidden md:table-cell' },
  { key: 'inicio', label: t('chamado.inicio'), class: 'hidden xl:table-cell' },
  { key: 'status', label: t('chamados.status') },
  { key: 'assignee', label: t('chamado.responsavel'), class: 'hidden sm:table-cell' },
  { key: 'team', label: t('chamado.grupo'), class: 'hidden lg:table-cell' },
  { key: 'movimento', label: t('chamados.ultimaMovimentacao'), class: 'hidden md:table-cell' },
  { key: 'horas', label: t('chamados.totalHoras'), class: 'hidden md:table-cell text-right' },
  { key: 'editar', label: t('chamados.editarColuna'), class: 'w-px text-right' },
])
const vazio = computed(() =>
  filtro.value.q ? t('chamados.vazio.busca') : t(`chamados.vazio.${aba.value.fila}`),
)

// Status em massa (docs/10 §10.6): supervisor (nos grupos que supervisiona) ou admin. A API
// confere cada chamado e devolve os que não mudaram, com o motivo.
const podeEmMassa = computed(
  () => auth.pode('ticket.bulk') || !!auth.me?.teams.some((g) => g.role === 'supervisor'),
)
const selecionados = ref(new Set<number>())
watch(filtro, () => (selecionados.value = new Set()))
function marcar(numero: number, sim: boolean) {
  const novo = new Set(selecionados.value)
  if (sim) novo.add(numero)
  else novo.delete(numero)
  selecionados.value = novo
}
const todosMarcados = computed({
  get: () => linhas.value.length > 0 && linhas.value.every((c) => selecionados.value.has(c.number)),
  set: (sim: boolean) => {
    selecionados.value = new Set(sim ? linhas.value.map((c) => c.number) : [])
  },
})
const statusLista = useStatus()
const opcoesNovoStatus = computed(() =>
  (statusLista.data.value ?? []).map((s) => ({ value: String(s.id), label: s.name })),
)
const novoStatus = ref('')
const emMassa = useStatusEmMassa()
async function mudarStatusEmMassa() {
  try {
    const r = await emMassa.mutateAsync({
      numeros: [...selecionados.value],
      status: Number(novoStatus.value),
    })
    if (r.updated.length)
      toast.show({ title: t('chamados.alteradosEmMassa', { n: r.updated.length }) })
    if (r.failed.length)
      toast.show({
        title: t('chamados.naoMudaram', {
          lista: r.failed.map((f) => `#${f.number} (${f.detail})`).join('; '),
        }),
        variant: 'error',
      })
    selecionados.value = new Set(r.failed.map((f) => f.number))
    novoStatus.value = ''
  } catch (e) {
    toast.show({ title: (e as Error).message, variant: 'error' })
  }
}
</script>

<template>
  <div :class="['mx-auto flex max-w-7xl flex-col gap-4', { 'pb-28': selecionados.size }]">
    <h1 class="text-xl font-semibold">{{ t('chamados.titulo') }}</h1>

    <TabsRoot :model-value="aba.slug" @update:model-value="(v) => filtrar('aba', String(v))">
      <TabsList
        class="flex flex-wrap gap-1 border-b border-border"
        :aria-label="t('chamados.filas')"
      >
        <TabsTrigger
          v-for="a in ABAS"
          :key="a.slug"
          :value="a.slug"
          class="-mb-px inline-flex items-center gap-2 border-b-2 border-transparent px-3 py-2 text-muted hover:text-fg data-[state=active]:border-primary data-[state=active]:font-medium data-[state=active]:text-fg"
        >
          {{ t(`chamados.abas.${a.fila}`) }}
          <span
            v-if="contagem(a.fila)"
            class="rounded-full bg-surface-raised px-2 text-sm tabular-nums"
          >
            {{ contagem(a.fila) }}
          </span>
        </TabsTrigger>
      </TabsList>

      <TabsContent :value="aba.slug" class="flex flex-col gap-4 pt-4">
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SelectField v-model="grupo" :label="t('chamado.grupo')" :options="opcoesGrupo" />
          <template v-if="emTodos">
            <SelectField v-model="status" :label="t('chamados.status')" :options="opcoesStatus" />
            <SelectField
              v-model="responsavel"
              :label="t('chamado.responsavel')"
              :options="opcoesResponsavel"
            />
          </template>
        </div>
        <div v-if="filtro.q" class="flex flex-wrap items-center gap-2">
          <span>{{ t('chamados.resultadosPara', { q: filtro.q }) }}</span>
          <Button size="sm" variant="ghost" @click="filtrar('q', null)">
            {{ t('chamados.limparBusca') }}
          </Button>
        </div>

        <p v-if="chamados.isPending.value" class="text-muted">{{ t('comum.carregando') }}</p>
        <p v-else-if="chamados.isError.value" class="text-danger">
          {{ t('comum.erroInesperado') }}
        </p>
        <template v-else>
          <DataTable
            :columns="colunas"
            :rows="linhas"
            row-key="id"
            :caption="t(`chamados.abas.${aba.fila}`)"
            :empty="vazio"
          >
            <template #head-sel>
              <Checkbox
                v-model="todosMarcados"
                :label="t('chamados.selecionarTodos')"
                ocultar-rotulo
              />
            </template>
            <template #cell-sel="{ row }">
              <Checkbox
                :model-value="selecionados.has(row.number)"
                :label="t('chamados.selecionar', { numero: row.number })"
                ocultar-rotulo
                @update:model-value="(sim) => marcar(row.number, sim)"
              />
            </template>
            <template #cell-horas="{ row }">
              {{ row.time_spent_minutes ? formatarDuracao(row.time_spent_minutes) : '—' }}
            </template>
            <template #head-editar>
              <span class="sr-only">{{ t('chamados.editarColuna') }}</span>
            </template>
            <template #cell-editar="{ row }">
              <RouterLink
                :to="`/chamados/${row.number}`"
                class="inline-flex size-8 items-center justify-center rounded-md border border-border-input text-fg hover:bg-surface-raised"
                :aria-label="t('chamados.editar', { numero: row.number })"
              >
                <Pencil class="size-4" aria-hidden="true" />
              </RouterLink>
            </template>
            <template #cell-number="{ row }">
              <RouterLink :to="`/chamados/${row.number}`" class="text-primary underline">
                {{ row.number }}
              </RouterLink>
            </template>
            <template #cell-title="{ row }">
              <span class="inline-flex items-center gap-2">
                <RouterLink :to="`/chamados/${row.number}`" class="font-medium hover:underline">
                  {{ row.title }}
                </RouterLink>
                <MessageCircle
                  v-if="row.has_news"
                  class="size-4 shrink-0 text-primary"
                  role="img"
                  :aria-label="t('chamados.novidade')"
                />
              </span>
            </template>
            <template #cell-client="{ row }">{{ row.client?.name ?? '—' }}</template>
            <template #cell-inicio="{ row }">
              <span class="tabular-nums">{{ formatarDataHora(row.started_at) }}</span>
            </template>
            <template #cell-status="{ row }">
              <StatusBadge :kind="row.status.kind" :label="row.status.name" />
            </template>
            <template #cell-assignee="{ row }">{{ row.assignee.display_name }}</template>
            <template #cell-team="{ row }">{{ row.team.name }}</template>
            <template #cell-movimento="{ row }">
              <span :title="formatarDataHora(row.updated_at) ?? undefined">
                {{ formatarHaQuanto(row.updated_at) }}
              </span>
            </template>
          </DataTable>
          <div v-if="chamados.hasNextPage.value" class="flex justify-center">
            <Button
              variant="secondary"
              :disabled="chamados.isFetchingNextPage.value"
              @click="chamados.fetchNextPage()"
            >
              {{ t('chamados.carregarMais') }}
            </Button>
          </div>
        </template>
      </TabsContent>
    </TabsRoot>

    <!-- Mudar o status dos selecionados: janela flutuante no pé da tela -->
    <Transition
      enter-from-class="translate-y-4 opacity-0"
      leave-to-class="translate-y-4 opacity-0"
      enter-active-class="motion-safe:transition"
      leave-active-class="motion-safe:transition"
    >
      <div
        v-if="selecionados.size"
        class="fixed inset-x-4 bottom-4 z-40 mx-auto flex max-w-3xl flex-wrap items-end gap-3 rounded-lg border border-border bg-surface p-4 shadow-xl"
        role="region"
        :aria-label="t('chamados.mudarStatus')"
      >
        <span class="self-center font-medium">
          {{ t('chamados.selecionados', { n: selecionados.size }) }}
        </span>
        <SelectField
          v-model="novoStatus"
          class="w-56"
          :label="t('chamados.novoStatus')"
          :options="opcoesNovoStatus"
        />
        <Button :disabled="!novoStatus || emMassa.isPending.value" @click="mudarStatusEmMassa">
          {{ t('chamados.mudarStatus') }}
        </Button>
        <Button variant="ghost" class="ml-auto" @click="selecionados = new Set()">
          {{ t('chamados.limparSelecao') }}
        </Button>
      </div>
    </Transition>
  </div>
</template>
