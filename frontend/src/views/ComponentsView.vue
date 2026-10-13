<script setup lang="ts">
import { ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import DataTable from '@/components/ui/DataTable.vue'
import Modal from '@/components/ui/Modal.vue'
import SelectField from '@/components/ui/SelectField.vue'
import StatusBadge, { type StatusKind } from '@/components/ui/StatusBadge.vue'
import TextField from '@/components/ui/TextField.vue'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'

/** Vitrine dos componentes de base (só em desenvolvimento), para conferir os dois temas. */
useHead('componentes.titulo')
const toast = useToast()
const titulo = ref('')
const grupo = ref<string>()
const modalAberto = ref(false)

const kinds: StatusKind[] = ['open', 'waiting', 'approval', 'closed', 'canceled']
const linhas: { numero: number; titulo: string; kind: StatusKind }[] = [
  { numero: 1240, titulo: 'ERP fora do ar', kind: 'open' },
  { numero: 1238, titulo: 'VPN do Rui não conecta', kind: 'waiting' },
  { numero: 1231, titulo: 'Renovar certificado do site', kind: 'closed' },
]
</script>

<template>
  <div class="mx-auto flex max-w-4xl flex-col gap-8">
    <div>
      <h1 class="text-xl font-semibold">{{ $t('componentes.titulo') }}</h1>
      <p class="mt-1 text-muted">{{ $t('componentes.descricao') }}</p>
    </div>

    <section class="flex flex-col gap-3">
      <h2 class="font-semibold">{{ $t('componentes.botoes') }}</h2>
      <div class="flex flex-wrap gap-2">
        <Button>Registrar</Button>
        <Button variant="secondary">Cancelar</Button>
        <Button variant="danger">Cancelar chamado</Button>
        <Button variant="ghost">Mais opções</Button>
        <Button disabled>Desabilitado</Button>
        <Button size="sm">Pequeno</Button>
      </div>
    </section>

    <section class="grid gap-4 sm:grid-cols-2">
      <h2 class="font-semibold sm:col-span-2">{{ $t('componentes.campos') }}</h2>
      <TextField
        v-model="titulo"
        :label="$t('componentes.exemploTitulo')"
        :hint="$t('componentes.exemploTituloDica')"
        required
      />
      <TextField
        :label="$t('componentes.exemploTitulo')"
        :error="$t('componentes.exemploErro')"
        model-value="Ab"
      />
      <SelectField
        v-model="grupo"
        :label="$t('componentes.exemploGrupo')"
        :options="[
          { value: 'suporte', label: 'TI – Suporte' },
          { value: 'infra', label: 'TI – Infraestrutura' },
        ]"
      />
    </section>

    <section class="flex flex-col gap-3">
      <h2 class="font-semibold">{{ $t('componentes.badges') }}</h2>
      <div class="flex flex-wrap gap-2">
        <StatusBadge v-for="k in kinds" :key="k" :kind="k" />
      </div>
    </section>

    <section class="flex flex-col gap-3">
      <h2 class="font-semibold">{{ $t('componentes.tabela') }}</h2>
      <DataTable
        :caption="$t('componentes.tabela')"
        row-key="numero"
        :rows="linhas"
        :columns="[
          { key: 'numero', label: $t('componentes.colunaNumero') },
          { key: 'titulo', label: $t('componentes.colunaTitulo') },
          { key: 'kind', label: $t('componentes.colunaStatus') },
        ]"
      >
        <template #cell-numero="{ row }">#{{ row.numero }}</template>
        <template #cell-kind="{ row }"><StatusBadge :kind="row.kind" /></template>
      </DataTable>
    </section>

    <section class="flex flex-wrap gap-6">
      <div class="flex flex-col gap-3">
        <h2 class="font-semibold">{{ $t('componentes.modal') }}</h2>
        <Button variant="secondary" @click="modalAberto = true">
          {{ $t('componentes.abrirModal') }}
        </Button>
        <Modal
          v-model:open="modalAberto"
          :title="$t('componentes.modalTitulo')"
          :description="$t('componentes.modalTexto')"
        >
          <template #actions>
            <Button variant="secondary" @click="modalAberto = false">
              {{ $t('comum.cancelar') }}
            </Button>
            <Button variant="danger" @click="modalAberto = false">
              {{ $t('comum.confirmar') }}
            </Button>
          </template>
        </Modal>
      </div>
      <div class="flex flex-col gap-3">
        <h2 class="font-semibold">{{ $t('componentes.toast') }}</h2>
        <Button
          variant="secondary"
          @click="
            toast.show({
              title: $t('componentes.avisoTitulo'),
              description: $t('componentes.avisoTexto'),
            })
          "
        >
          {{ $t('componentes.mostrarAviso') }}
        </Button>
      </div>
    </section>
  </div>
</template>
