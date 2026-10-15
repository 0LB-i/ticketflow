<script setup lang="ts">
import { computed, ref } from 'vue'

/**
 * Colunas de uma série só ao longo do tempo (horas por dia ou por semana). Passar o mouse ou o
 * foco numa coluna mostra a data e o valor; o eixo mostra três marcas em horas cheias.
 */
const props = defineProps<{
  titulo: string
  pontos: { chave: string; rotulo: string; valor: number }[]
  formatar: (valor: number) => string
}>()

// Topo do eixo em horas cheias e pares, para as marcas (0, metade, topo) ficarem redondas.
const topo = computed(() => {
  const max = Math.max(0, ...props.pontos.map((p) => p.valor))
  return Math.max(120, Math.ceil(max / 120) * 120)
})
const marcas = computed(() => [topo.value, topo.value / 2, 0])
// Só alguns rótulos no eixo de baixo: o primeiro e mais uns cinco, espaçados.
const passoRotulo = computed(() => Math.max(1, Math.ceil(props.pontos.length / 6)))
const ativo = ref<number | null>(null)
</script>

<template>
  <figure class="flex flex-col gap-3">
    <figcaption class="font-medium">{{ titulo }}</figcaption>
    <div class="grid grid-cols-[auto_1fr] gap-x-2">
      <div class="flex h-40 flex-col justify-between text-xs text-muted tabular-nums">
        <span v-for="m in marcas" :key="m" class="-my-2 text-right">{{ formatar(m) }}</span>
      </div>
      <div class="relative h-40">
        <div
          v-for="m in marcas"
          :key="m"
          class="absolute inset-x-0 border-t border-border"
          :style="{ bottom: `${(m / topo) * 100}%` }"
          aria-hidden="true"
        />
        <ul class="absolute inset-0 flex items-end gap-0.5">
          <li
            v-for="(p, i) in pontos"
            :key="p.chave"
            class="relative flex h-full flex-1 items-end justify-center"
            tabindex="0"
            :aria-label="`${p.rotulo}: ${formatar(p.valor)}`"
            @pointerenter="ativo = i"
            @pointerleave="ativo = null"
            @focus="ativo = i"
            @blur="ativo = null"
          >
            <span
              class="w-full max-w-6 rounded-t bg-primary"
              :class="{ 'opacity-80': ativo === i }"
              :style="{ height: `${(p.valor / topo) * 100}%` }"
              aria-hidden="true"
            />
            <span
              v-if="ativo === i"
              class="absolute bottom-full z-10 mb-1 rounded-md border border-border bg-surface px-2 py-1 text-sm whitespace-nowrap shadow-lg"
              role="tooltip"
            >
              <strong class="tabular-nums">{{ formatar(p.valor) }}</strong>
              <span class="text-muted"> · {{ p.rotulo }}</span>
            </span>
          </li>
        </ul>
      </div>
      <div />
      <div class="flex gap-0.5 pt-1 text-xs text-muted" aria-hidden="true">
        <span v-for="(p, i) in pontos" :key="p.chave" class="flex-1 overflow-visible">
          <span v-if="i % passoRotulo === 0" class="whitespace-nowrap">{{ p.rotulo }}</span>
        </span>
      </div>
    </div>
  </figure>
</template>
