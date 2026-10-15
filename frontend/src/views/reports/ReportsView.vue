<script setup lang="ts">
import { Download } from 'lucide-vue-next'
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import BarChart from '@/components/reports/BarChart.vue'
import ColumnChart from '@/components/reports/ColumnChart.vue'
import ClientPicker from '@/components/tickets/ClientPicker.vue'
import Button from '@/components/ui/Button.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SelectField from '@/components/ui/SelectField.vue'
import TextField from '@/components/ui/TextField.vue'
import { dataEHora, formatarDataHora, formatarDuracao } from '@/composables/formato'
import {
  baixarPdf,
  type FiltroRelatorio,
  type Relatorio,
  useOpcoesRelatorio,
  useRelatorio,
} from '@/composables/relatorios'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'
import { idiomaAtual } from '@/i18n'

/**
 * Relatórios (docs/14 §14.7): horas por pessoa, por cliente e por dia, horas extras (tempo de
 * tarefa fora do expediente) e o PDF com os mesmos filtros. Cada um vê o próprio trabalho; o
 * supervisor, o dos grupos que supervisiona; admin e auditor, tudo (a API decide).
 */
useHead('relatorios.titulo')
const { t } = useI18n()
const toast = useToast()
const opcoes = useOpcoesRelatorio()

const TODOS = '*'
const hoje = dataEHora(new Date()).data

// --- período ---
function ultimoDia(ano: number, mes: number) {
  return new Date(Date.UTC(ano, mes, 0)).getUTCDate()
}
const meses = computed(() => {
  const [ano, mes] = hoje.split('-').map(Number) as [number, number]
  const nome = new Intl.DateTimeFormat(idiomaAtual(), {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  })
  return Array.from({ length: 12 }, (_, i) => {
    const data = new Date(Date.UTC(ano, mes - 1 - i, 1))
    const a = data.getUTCFullYear()
    const m = data.getUTCMonth() + 1
    const mm = String(m).padStart(2, '0')
    return {
      value: `${a}-${mm}`,
      label: nome.format(data),
      start: `${a}-${mm}-01`,
      end: `${a}-${mm}-${ultimoDia(a, m)}`,
    }
  })
})
const periodo = ref(meses.value[0]!.value)
const inicio = ref(meses.value[0]!.start)
const fim = ref(hoje)
const opcoesPeriodo = computed(() => [
  ...meses.value.map(({ value, label }) => ({ value, label })),
  { value: 'personalizado', label: t('relatorios.personalizado') },
])

// --- filtros ---
const grupo = ref(TODOS)
const pessoa = ref(TODOS)
const cliente = ref<{ id: string; name: string } | null>(null)
const opcoesGrupo = computed(() => [
  { value: TODOS, label: t('relatorios.todosOsGrupos') },
  ...(opcoes.data.value?.teams ?? []).map((g) => ({ value: g.id, label: g.name })),
])
const opcoesPessoa = computed(() => [
  { value: TODOS, label: t('relatorios.todasAsPessoas') },
  ...(opcoes.data.value?.people ?? []).map((p) => ({ value: p.id, label: p.name })),
])
// Quem só vê o próprio trabalho não tem o que escolher em grupo e pessoa.
const escolhePessoas = computed(() => (opcoes.data.value?.people.length ?? 0) > 1)

const periodoValido = computed(() =>
  Boolean(inicio.value && fim.value && inicio.value <= fim.value),
)
const filtro = computed<FiltroRelatorio>(() => {
  const mes = meses.value.find((m) => m.value === periodo.value)
  const f: FiltroRelatorio = mes
    ? { start: mes.start, end: mes.end }
    : { start: inicio.value, end: fim.value }
  if (grupo.value !== TODOS) f.team = grupo.value
  if (pessoa.value !== TODOS) f.person = pessoa.value
  if (cliente.value) f.client = cliente.value.id
  return f
})
const relatorio = useRelatorio(filtro)
const dados = computed(() => relatorio.data.value)

const gerando = ref(false)
async function pdf() {
  gerando.value = true
  try {
    await baixarPdf(filtro.value)
  } catch (e) {
    toast.show({ title: (e as Error).message, variant: 'error' })
  } finally {
    gerando.value = false
  }
}

// --- números ---
const horas = formatarDuracao
const numero = (n: number) => n.toLocaleString(idiomaAtual())

const cartoes = computed(() => {
  const tot = dados.value?.totals
  if (!tot) return []
  return [
    { chave: 'horas', valor: horas(tot.minutes) },
    { chave: 'horasExtras', valor: horas(tot.overtime_minutes) },
    { chave: 'tarefas', valor: numero(tot.tasks) },
    { chave: 'registrados', valor: numero(tot.tickets_opened) },
    { chave: 'concluidos', valor: numero(tot.tickets_closed) },
  ]
})

/** Até dois meses, uma coluna por dia; mais que isso, por semana (a partir do primeiro dia). */
function serie(dias: Relatorio['days'], campo: 'minutes' | 'overtime_minutes') {
  const curto = new Intl.DateTimeFormat(idiomaAtual(), {
    day: '2-digit',
    month: '2-digit',
    timeZone: 'UTC',
  })
  const rotulo = (iso: string) => curto.format(new Date(`${iso}T00:00:00Z`))
  const tamanho = dias.length > 62 ? 7 : 1
  const pontos = []
  for (let i = 0; i < dias.length; i += tamanho) {
    const grupoDias = dias.slice(i, i + tamanho)
    pontos.push({
      chave: grupoDias[0]!.date,
      rotulo: rotulo(grupoDias[0]!.date),
      valor: grupoDias.reduce((soma, d) => soma + d[campo], 0),
    })
  }
  return pontos
}
const porDia = computed(() => serie(dados.value?.days ?? [], 'minutes'))
const extrasPorDia = computed(() => serie(dados.value?.days ?? [], 'overtime_minutes'))
const porSemana = computed(() => (dados.value?.days.length ?? 0) > 62)

const pessoas = computed(() => dados.value?.people ?? [])
const barrasPessoas = computed(() =>
  pessoas.value.map((p) => ({ chave: p.id, rotulo: p.name, valor: p.minutes })),
)
const barrasExtras = computed(() =>
  pessoas.value
    .filter((p) => p.overtime_minutes > 0)
    .sort((a, b) => b.overtime_minutes - a.overtime_minutes)
    .map((p) => ({ chave: p.id, rotulo: p.name, valor: p.overtime_minutes })),
)
const clientes = computed(() =>
  (dados.value?.clients ?? []).map((c) => ({
    ...c,
    chave: c.id ?? 'sem-cliente',
    nome: c.name ?? t('relatorios.semCliente'),
  })),
)
const barrasClientes = computed(() =>
  clientes.value
    .filter((c) => c.minutes > 0)
    .slice(0, 10)
    .map((c) => ({ chave: c.chave, rotulo: c.nome, valor: c.minutes })),
)
const tarefasExtras = computed(() =>
  (dados.value?.overtime_tasks ?? []).map((o, i) => ({ ...o, chave: i })),
)

const DIAS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'dom'] as const
const expediente = computed(() => {
  const wh = dados.value?.work_hours
  if (!wh) return ''
  const dias = wh.weekdays.map((d) => t(`expediente.diasCurtos.${DIAS[d]}`)).join(', ')
  return t('relatorios.expedienteUsado', {
    dias,
    inicio: wh.start.slice(0, 5),
    fim: wh.end.slice(0, 5),
  })
})

const colunasPessoas = computed(() => [
  { key: 'name', label: t('relatorios.colunas.pessoa') },
  { key: 'minutes', label: t('relatorios.colunas.horas') },
  { key: 'overtime_minutes', label: t('relatorios.colunas.horasExtras') },
  { key: 'tasks', label: t('relatorios.colunas.tarefas') },
  { key: 'tickets_closed', label: t('relatorios.colunas.concluidos') },
])
const colunasClientes = computed(() => [
  { key: 'nome', label: t('relatorios.colunas.cliente') },
  { key: 'minutes', label: t('relatorios.colunas.horas') },
  { key: 'tickets_opened', label: t('relatorios.colunas.registrados') },
  { key: 'tickets_closed', label: t('relatorios.colunas.concluidos') },
])
const colunasExtras = computed(() => [
  { key: 'done_at', label: t('relatorios.colunas.quando') },
  { key: 'person', label: t('relatorios.colunas.pessoa') },
  { key: 'ticket', label: t('relatorios.colunas.chamado') },
  { key: 'minutes', label: t('relatorios.colunas.tempo') },
  { key: 'overtime_minutes', label: t('relatorios.colunas.foraDoExpediente') },
])

const aba = ref('produtividade')
const ABAS = ['produtividade', 'clientes', 'horasExtras'] as const
</script>

<template>
  <div class="mx-auto flex max-w-7xl flex-col gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold">{{ t('relatorios.titulo') }}</h1>
        <p class="mt-1 text-muted">{{ t('relatorios.descricao') }}</p>
      </div>
      <Button variant="secondary" :disabled="gerando || !periodoValido" @click="pdf">
        <Download class="size-4" aria-hidden="true" />
        {{ gerando ? t('relatorios.gerandoPdf') : t('relatorios.baixarPdf') }}
      </Button>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <SelectField v-model="periodo" :label="t('relatorios.periodo')" :options="opcoesPeriodo" />
      <template v-if="periodo === 'personalizado'">
        <TextField v-model="inicio" type="date" :label="t('relatorios.de')" />
        <TextField
          v-model="fim"
          type="date"
          :label="t('relatorios.ate')"
          :error="periodoValido ? undefined : t('relatorios.periodoInvalido')"
        />
      </template>
      <SelectField
        v-if="opcoesGrupo.length > 1"
        v-model="grupo"
        :label="t('relatorios.grupo')"
        :options="opcoesGrupo"
      />
      <SelectField
        v-if="escolhePessoas"
        v-model="pessoa"
        :label="t('relatorios.pessoa')"
        :options="opcoesPessoa"
      />
      <ClientPicker v-model="cliente" :label="t('relatorios.cliente')" />
    </div>

    <p v-if="relatorio.isPending.value" class="text-muted">{{ t('comum.carregando') }}</p>
    <p v-else-if="relatorio.isError.value" class="text-danger" role="alert">
      {{ relatorio.error.value?.message ?? t('comum.erroInesperado') }}
    </p>
    <div
      v-else-if="dados"
      class="flex flex-col gap-4 transition-opacity"
      :class="{ 'opacity-60': relatorio.isPlaceholderData.value }"
    >
      <dl class="grid grid-cols-2 gap-3 md:grid-cols-5">
        <div
          v-for="c in cartoes"
          :key="c.chave"
          class="rounded-lg border border-border bg-surface p-4"
        >
          <dt class="text-muted">{{ t(`relatorios.cartoes.${c.chave}`) }}</dt>
          <dd class="mt-1 text-2xl font-semibold">{{ c.valor }}</dd>
        </div>
      </dl>

      <TabsRoot v-model="aba">
        <TabsList
          class="flex flex-wrap gap-1 border-b border-border"
          :aria-label="t('relatorios.titulo')"
        >
          <TabsTrigger
            v-for="a in ABAS"
            :key="a"
            :value="a"
            class="-mb-px inline-flex items-center gap-2 border-b-2 border-transparent px-3 py-2 text-muted hover:text-fg data-[state=active]:border-primary data-[state=active]:font-medium data-[state=active]:text-fg"
          >
            {{ t(`relatorios.abas.${a}`) }}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="produtividade" class="flex flex-col gap-4 pt-4">
          <div class="grid gap-4 lg:grid-cols-2">
            <div class="rounded-lg border border-border bg-surface p-4">
              <ColumnChart
                :titulo="t(porSemana ? 'relatorios.horasPorSemana' : 'relatorios.horasPorDia')"
                :pontos="porDia"
                :formatar="horas"
              />
            </div>
            <div class="rounded-lg border border-border bg-surface p-4">
              <BarChart
                :titulo="t('relatorios.horasPorPessoa')"
                :itens="barrasPessoas"
                :formatar="horas"
              />
              <p v-if="!barrasPessoas.length" class="text-muted">{{ t('relatorios.vazio') }}</p>
            </div>
          </div>
          <DataTable
            :columns="colunasPessoas"
            :rows="pessoas"
            row-key="id"
            :caption="t('relatorios.horasPorPessoa')"
            :empty="t('relatorios.vazio')"
          >
            <template #cell-minutes="{ row }">{{ horas(row.minutes) }}</template>
            <template #cell-overtime_minutes="{ row }">{{ horas(row.overtime_minutes) }}</template>
          </DataTable>
        </TabsContent>

        <TabsContent value="clientes" class="flex flex-col gap-4 pt-4">
          <div v-if="barrasClientes.length" class="rounded-lg border border-border bg-surface p-4">
            <BarChart
              :titulo="t('relatorios.horasPorCliente')"
              :itens="barrasClientes"
              :formatar="horas"
            />
          </div>
          <DataTable
            :columns="colunasClientes"
            :rows="clientes"
            row-key="chave"
            :caption="t('relatorios.horasPorCliente')"
            :empty="t('relatorios.vazio')"
          >
            <template #cell-minutes="{ row }">{{ horas(row.minutes) }}</template>
          </DataTable>
        </TabsContent>

        <TabsContent value="horasExtras" class="flex flex-col gap-4 pt-4">
          <p class="text-muted">{{ expediente }}</p>
          <div class="grid gap-4 lg:grid-cols-2">
            <div class="rounded-lg border border-border bg-surface p-4">
              <ColumnChart
                :titulo="
                  t(porSemana ? 'relatorios.horasExtrasPorSemana' : 'relatorios.horasExtrasPorDia')
                "
                :pontos="extrasPorDia"
                :formatar="horas"
              />
            </div>
            <div class="rounded-lg border border-border bg-surface p-4">
              <BarChart
                :titulo="t('relatorios.horasExtrasPorPessoa')"
                :itens="barrasExtras"
                :formatar="horas"
              />
              <p v-if="!barrasExtras.length" class="text-muted">{{ t('relatorios.semExtras') }}</p>
            </div>
          </div>
          <DataTable
            :columns="colunasExtras"
            :rows="tarefasExtras"
            row-key="chave"
            :caption="t('relatorios.tarefasForaDoExpediente')"
            :empty="t('relatorios.semExtras')"
          >
            <template #cell-done_at="{ row }">{{ formatarDataHora(row.done_at) }}</template>
            <template #cell-ticket="{ row }">
              <RouterLink :to="`/chamados/${row.ticket_number}`" class="text-primary underline">
                #{{ row.ticket_number }}
              </RouterLink>
              {{ row.ticket_title }}
            </template>
            <template #cell-minutes="{ row }">{{ horas(row.minutes) }}</template>
            <template #cell-overtime_minutes="{ row }">{{ horas(row.overtime_minutes) }}</template>
          </DataTable>
        </TabsContent>
      </TabsRoot>
    </div>
  </div>
</template>
