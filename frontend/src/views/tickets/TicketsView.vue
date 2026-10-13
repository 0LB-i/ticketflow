<script setup lang="ts">
import { MessageCircle } from 'lucide-vue-next'
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { type LocationQueryRaw, useRoute, useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SelectField from '@/components/ui/SelectField.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useGrupos } from '@/composables/admin'
import {
  chamadosApi,
  type Fila,
  type FiltroChamados,
  useAcaoNoChamado,
  useChamados,
  useContagens,
} from '@/composables/chamados'
import { formatarDataHora, formatarHaQuanto } from '@/composables/formato'
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

const ABAS: { slug: string; fila: Fila }[] = [
  { slug: 'nao-atribuidos', fila: 'unassigned' },
  { slug: 'meus', fila: 'mine' },
  { slug: 'novidades', fila: 'news' },
  { slug: 'aguardando', fila: 'waiting' },
  { slug: 'acompanhando', fila: 'watching' },
  { slug: 'todos', fila: 'all' },
]
// Opção "todos" dos filtros (não vai para a URL).
const TODOS = '*'
const KINDS = ['open', 'waiting', 'closed', 'canceled'] as const
const RESPONSAVEL = { eu: 'me', ninguem: 'none' } as const

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
  { value: 'ninguem', label: t('chamados.filtros.ninguem') },
])

const contagem = (fila: Fila) => (fila === 'all' ? null : (contagens.data.value?.[fila] ?? null))

const colunas = computed(() => [
  { key: 'number', label: t('chamados.numero') },
  { key: 'title', label: t('chamados.tituloColuna') },
  { key: 'client', label: t('chamado.cliente'), class: 'hidden md:table-cell' },
  { key: 'inicio', label: t('chamado.inicio'), class: 'hidden xl:table-cell' },
  { key: 'status', label: t('chamados.status') },
  { key: 'assignee', label: t('chamado.responsavel'), class: 'hidden sm:table-cell' },
  { key: 'team', label: t('chamado.grupo'), class: 'hidden lg:table-cell' },
  { key: 'movimento', label: t('chamados.ultimaMovimentacao'), class: 'hidden md:table-cell' },
])
const vazio = computed(() =>
  filtro.value.q ? t('chamados.vazio.busca') : t(`chamados.vazio.${aba.value.fila}`),
)

// "Pegar o próximo" (docs/10 §10.6): da fila Não atribuídos, no grupo do filtro ou em todos.
const podePegar = computed(() => auth.pode('ticket.assign_self') && !!auth.me?.teams.length)
const pegar = useAcaoNoChamado('proximo', chamadosApi.pegarProximo)
async function pegarProximo() {
  try {
    const chamado = await pegar.mutateAsync(texto('grupo'))
    toast.show({
      title: t('chamados.pegou', { numero: chamado.number }),
      description: chamado.title,
    })
    await router.push(`/chamados/${chamado.number}`)
  } catch (e) {
    toast.show({ title: (e as Error).message, variant: 'error' })
  }
}
</script>

<template>
  <div class="mx-auto flex max-w-7xl flex-col gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="text-xl font-semibold">{{ t('chamados.titulo') }}</h1>
      <Button v-if="podePegar" :disabled="pegar.isPending.value" @click="pegarProximo">
        {{ t('chamados.pegarProximo') }}
      </Button>
    </div>

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
            <template #cell-assignee="{ row }">{{ row.assignee?.full_name ?? '—' }}</template>
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
  </div>
</template>
