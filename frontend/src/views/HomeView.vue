<script setup lang="ts">
import { useHead } from '@/composables/useHead'
import Button from '@/components/ui/Button.vue'
import { useHealth } from '@/composables/useHealth'

useHead('inicio.titulo')
const { data, isPending, isError, refetch } = useHealth()
</script>

<template>
  <div class="mx-auto flex max-w-3xl flex-col gap-6">
    <div>
      <h1 class="text-xl font-semibold">{{ $t('inicio.boasVindas') }}</h1>
      <p class="mt-1 text-muted">{{ $t('inicio.emConstrucao') }}</p>
    </div>

    <section
      class="rounded-lg border border-border bg-surface p-4"
      aria-labelledby="estado-titulo"
      aria-live="polite"
    >
      <h2 id="estado-titulo" class="font-semibold">{{ $t('inicio.estadoDoSistema') }}</h2>
      <p v-if="isPending" class="mt-2 text-muted">{{ $t('inicio.verificando') }}</p>
      <div v-else-if="isError" class="mt-2 flex flex-wrap items-center gap-3">
        <p class="text-danger">{{ $t('inicio.erroAoConsultar') }}</p>
        <Button variant="secondary" size="sm" @click="refetch()">
          {{ $t('inicio.tentarDeNovo') }}
        </Button>
      </div>
      <dl v-else-if="data" class="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1">
        <dt class="text-muted">{{ $t('inicio.estadoDoSistema') }}</dt>
        <dd class="font-medium text-green-fg">{{ $t('inicio.funcionando') }}</dd>
        <dt class="text-muted">{{ $t('inicio.versao') }}</dt>
        <dd class="tabular-nums">{{ data.version }}</dd>
        <dt class="text-muted">{{ $t('inicio.banco') }}</dt>
        <dd>{{ data.database }}</dd>
      </dl>
    </section>
  </div>
</template>
