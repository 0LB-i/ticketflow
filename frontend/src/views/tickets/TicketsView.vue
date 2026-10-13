<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Button from '@/components/ui/Button.vue'
import DataTable from '@/components/ui/DataTable.vue'
import PriorityBadge, { type Prioridade } from '@/components/ui/PriorityBadge.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useChamados } from '@/composables/chamados'
import { formatarDataHora } from '@/composables/formato'
import { useHead } from '@/composables/useHead'

/**
 * Chamados que o usuário vê, na ordenação padrão (prioridade, depois o mais antigo).
 * As abas das filas e os filtros entram na Sprint 4 (F1-S4-05).
 */
useHead('chamados.titulo')
const { t } = useI18n()
const chamados = useChamados()

const linhas = computed(() => chamados.data.value?.pages.flatMap((p) => p.items) ?? [])
const colunas = computed(() => [
  { key: 'number', label: t('chamados.numero') },
  { key: 'title', label: t('chamados.tituloColuna') },
  { key: 'client', label: t('chamado.cliente'), class: 'hidden md:table-cell' },
  { key: 'inicio', label: t('chamado.inicio'), class: 'hidden lg:table-cell' },
  { key: 'priority', label: t('chamado.prioridade') },
  { key: 'status', label: t('chamados.status') },
  { key: 'assignee', label: t('chamado.responsavel'), class: 'hidden sm:table-cell' },
  { key: 'team', label: t('chamado.grupo'), class: 'hidden md:table-cell' },
])
</script>

<template>
  <div class="mx-auto flex max-w-6xl flex-col gap-4">
    <h1 class="text-xl font-semibold">{{ t('chamados.titulo') }}</h1>

    <p v-if="chamados.isPending.value" class="text-muted">{{ t('comum.carregando') }}</p>
    <p v-else-if="chamados.isError.value" class="text-danger">{{ t('comum.erroInesperado') }}</p>
    <template v-else>
      <DataTable :columns="colunas" :rows="linhas" row-key="id" :caption="t('chamados.titulo')">
        <template #cell-number="{ row }">
          <RouterLink :to="`/chamados/${row.number}`" class="text-primary underline">
            {{ row.number }}
          </RouterLink>
        </template>
        <template #cell-title="{ row }">
          <RouterLink :to="`/chamados/${row.number}`" class="font-medium hover:underline">
            {{ row.title }}
          </RouterLink>
        </template>
        <template #cell-client="{ row }">{{ row.client?.name ?? '—' }}</template>
        <template #cell-inicio="{ row }">
          <span class="tabular-nums">{{ formatarDataHora(row.started_at) }}</span>
        </template>
        <template #cell-priority="{ row }">
          <PriorityBadge :priority="row.priority as Prioridade" />
        </template>
        <template #cell-status="{ row }">
          <StatusBadge :kind="row.status.kind" :label="row.status.name" />
        </template>
        <template #cell-assignee="{ row }">{{ row.assignee?.full_name ?? '—' }}</template>
        <template #cell-team="{ row }">{{ row.team.name }}</template>
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
  </div>
</template>
