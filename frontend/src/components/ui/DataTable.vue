<script setup lang="ts" generic="T extends Record<string, unknown>">
/**
 * Tabela simples com cabeçalho e células por slot (`#cell-<chave>`). A chave pode ser um campo
 * da linha (mostrado direto) ou uma coluna calculada, preenchida só pelo slot. `class` vai no
 * cabeçalho e nas células da coluna (ex.: "hidden md:table-cell" esconde a coluna no celular).
 * Ordenação e paginação entram com o TanStack Table quando as filas existirem (Sprint 4).
 */
defineProps<{
  columns: { key: string; label: string; class?: string }[]
  rows: T[]
  rowKey: keyof T & string
  caption?: string
  /** Texto da tabela vazia; sem ele, "Nenhum registro". */
  empty?: string
}>()
</script>

<template>
  <div class="overflow-x-auto rounded-lg border border-border bg-surface">
    <table class="w-full border-collapse text-left">
      <caption v-if="caption" class="sr-only">
        {{
          caption
        }}
      </caption>
      <thead class="bg-surface-raised text-muted">
        <tr>
          <th
            v-for="col in columns"
            :key="col.key"
            scope="col"
            :class="['px-3 py-2 font-medium', col.class]"
          >
            {{ col.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row[rowKey])" class="border-t border-border">
          <td v-for="col in columns" :key="col.key" :class="['px-3 py-2 tabular-nums', col.class]">
            <slot :name="`cell-${col.key}`" :row="row">{{ row[col.key as keyof T] }}</slot>
          </td>
        </tr>
        <tr v-if="rows.length === 0">
          <td :colspan="columns.length" class="px-3 py-6 text-center text-muted">
            {{ empty ?? $t('comum.nenhumRegistro') }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
