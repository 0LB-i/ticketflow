<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Checkbox from '@/components/ui/Checkbox.vue'
import DataTable from '@/components/ui/DataTable.vue'
import TextField from '@/components/ui/TextField.vue'
import { useClientes } from '@/composables/clientes'
import { formatarDocumento, formatarTelefone } from '@/composables/documentos'
import { useHead } from '@/composables/useHead'
import { useAuthStore } from '@/stores/auth'

/** Clientes atendidos, pessoa física e jurídica. A busca vai para a API (nome, CPF/CNPJ, e-mail). */
useHead('clientes.titulo')
const { t } = useI18n()
const auth = useAuthStore()

const busca = ref('')
const termo = ref('')
const inativos = ref(false)
// Espera a pessoa parar de digitar antes de consultar.
let espera: ReturnType<typeof setTimeout> | undefined
watch(busca, (valor) => {
  clearTimeout(espera)
  espera = setTimeout(() => (termo.value = valor), 300)
})
onBeforeUnmount(() => clearTimeout(espera))

const clientes = useClientes(() => ({ q: termo.value, inativos: inativos.value }))
const linhas = computed(() => clientes.data.value?.items ?? [])
const colunas = computed(() => [
  { key: 'name', label: t('clientes.nome') },
  { key: 'document', label: t('clientes.documento') },
  { key: 'kind', label: t('clientes.tipo'), class: 'hidden md:table-cell' },
  { key: 'phone', label: t('clientes.telefone') },
  { key: 'email', label: t('clientes.email'), class: 'hidden lg:table-cell' },
  { key: 'cidade', label: t('clientes.cidade'), class: 'hidden lg:table-cell' },
])
</script>

<template>
  <div class="mx-auto flex max-w-7xl flex-col gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="text-xl font-semibold">{{ t('clientes.titulo') }}</h1>
      <Button v-if="auth.pode('client.manage')" @click="$router.push('/admin/clientes/novo')">
        {{ t('clientes.novo') }}
      </Button>
    </div>

    <div class="flex flex-wrap items-end gap-4">
      <div class="w-full max-w-md">
        <TextField
          v-model="busca"
          :label="t('comum.buscar')"
          :hint="t('clientes.buscaDica')"
          type="search"
        />
      </div>
      <div class="pb-7"><Checkbox v-model="inativos" :label="t('comum.mostrarInativos')" /></div>
    </div>

    <p v-if="clientes.isPending.value" class="text-muted">{{ t('comum.carregando') }}</p>
    <p v-else-if="clientes.isError.value" class="text-danger">{{ t('comum.erroInesperado') }}</p>
    <template v-else>
      <DataTable :columns="colunas" :rows="linhas" row-key="id" :caption="t('clientes.titulo')">
        <template #cell-name="{ row }">
          <RouterLink :to="`/admin/clientes/${row.id}`" class="font-medium hover:underline">
            {{ row.label }}
          </RouterLink>
          <span v-if="row.name && row.trade_name" class="block text-muted">{{
            row.trade_name
          }}</span>
          <Badge v-if="!row.is_active" color="gray" class="ml-2">{{ t('comum.inativo') }}</Badge>
        </template>
        <template #cell-document="{ row }">{{
          row.document ? formatarDocumento(row.document, row.kind) : '—'
        }}</template>
        <template #cell-kind="{ row }">{{ t(`clientes.tipos.${row.kind}`) }}</template>
        <template #cell-phone="{ row }">{{
          row.phones.length ? formatarTelefone(row.phones[0]) : '—'
        }}</template>
        <template #cell-email="{ row }">{{ row.emails[0] ?? '—' }}</template>
        <template #cell-cidade="{ row }">{{ row.city }}/{{ row.state }}</template>
      </DataTable>
      <p v-if="!linhas.length" class="text-muted">{{ t('comum.nenhumRegistro') }}</p>
      <p v-else class="text-muted">
        {{
          clientes.data.value!.total > linhas.length
            ? t('clientes.mostrandoDe', { n: linhas.length, total: clientes.data.value!.total })
            : t('clientes.total', { n: linhas.length })
        }}
      </p>
    </template>
  </div>
</template>
