<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Checkbox from '@/components/ui/Checkbox.vue'
import SelectField from '@/components/ui/SelectField.vue'
import SidePanel from '@/components/ui/SidePanel.vue'
import TextField from '@/components/ui/TextField.vue'
import { type Setor, setoresApi, useAlteracao, useSetores } from '@/composables/admin'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'

useHead('setores.titulo')
const { t } = useI18n()
const toast = useToast()
const setores = useSetores()
const NENHUM = '__nenhum__' // o Select não aceita valor vazio

const mostrarInativos = ref(false)

/** Árvore achatada na ordem de exibição, com a profundidade de cada setor. */
const arvore = computed(() => {
  const todos = (setores.data.value ?? []).filter((s) => mostrarInativos.value || s.is_active)
  const filhos = new Map<string | null, Setor[]>()
  for (const s of todos) {
    const pai = todos.some((p) => p.id === s.parent_id) ? s.parent_id : null
    filhos.set(pai, [...(filhos.get(pai) ?? []), s])
  }
  const linhas: { setor: Setor; nivel: number }[] = []
  const visitar = (pai: string | null, nivel: number) => {
    for (const s of filhos.get(pai) ?? []) {
      linhas.push({ setor: s, nivel })
      visitar(s.id, nivel + 1)
    }
  }
  visitar(null, 0)
  return linhas
})

const painel = ref(false)
const editando = ref<Setor | null>(null)
const form = reactive({ name: '', code: '', parent: NENHUM, is_active: true })
const erro = ref<string | null>(null)

/** Opções de "setor acima": nunca o próprio setor nem os subsetores dele. */
const opcoesAcima = computed(() => {
  const todos = setores.data.value ?? []
  const bloqueados = new Set<string>()
  if (editando.value) {
    bloqueados.add(editando.value.id)
    let mudou = true
    while (mudou) {
      mudou = false
      for (const s of todos) {
        if (s.parent_id && bloqueados.has(s.parent_id) && !bloqueados.has(s.id)) {
          bloqueados.add(s.id)
          mudou = true
        }
      }
    }
  }
  return [
    { value: NENHUM, label: t('setores.nenhumAcima') },
    ...todos
      .filter((s) => s.is_active && !bloqueados.has(s.id))
      .map((s) => ({ value: s.id, label: s.name })),
  ]
})

function abrir(s: Setor | null) {
  editando.value = s
  Object.assign(form, {
    name: s?.name ?? '',
    code: s?.code ?? '',
    parent: s?.parent_id ?? NENHUM,
    is_active: s?.is_active ?? true,
  })
  erro.value = null
  painel.value = true
}

const criar = useAlteracao(setoresApi.criar, ['setores'])
const editar = useAlteracao(setoresApi.editar, ['setores'])

async function salvar() {
  erro.value = null
  const dados = {
    name: form.name,
    code: form.code.trim() || null,
    parent_id: form.parent === NENHUM ? null : form.parent,
  }
  try {
    if (editando.value) {
      await editar.mutateAsync({ id: editando.value.id, ...dados, is_active: form.is_active })
      toast.show({ title: t('comum.salvo') })
    } else {
      await criar.mutateAsync(dados)
      toast.show({ title: t('setores.criado') })
    }
    painel.value = false
  } catch (e) {
    erro.value = (e as Error).message
  }
}
</script>

<template>
  <div class="mx-auto flex max-w-3xl flex-col gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold">{{ $t('setores.titulo') }}</h1>
        <p class="mt-1 text-muted">{{ $t('setores.descricao') }}</p>
      </div>
      <Button @click="abrir(null)">{{ $t('setores.novo') }}</Button>
    </div>
    <Checkbox v-model="mostrarInativos" :label="$t('comum.mostrarInativos')" />

    <p v-if="setores.isPending.value" class="text-muted">{{ $t('comum.carregando') }}</p>
    <p v-else-if="!arvore.length" class="text-muted">{{ $t('setores.vazio') }}</p>
    <ul
      v-else
      class="divide-y divide-border rounded-lg border border-border bg-surface"
      role="tree"
    >
      <li
        v-for="{ setor, nivel } in arvore"
        :key="setor.id"
        role="treeitem"
        :aria-level="nivel + 1"
        class="flex items-center gap-2 py-2 pr-3"
        :style="{ paddingLeft: `${0.75 + nivel * 1.5}rem` }"
      >
        <span v-if="nivel" class="text-muted" aria-hidden="true">↳</span>
        <button type="button" class="font-medium text-primary underline" @click="abrir(setor)">
          {{ setor.name }}
        </button>
        <span v-if="setor.code" class="font-mono text-xs text-muted">{{ setor.code }}</span>
        <Badge v-if="!setor.is_active" color="gray" class="ml-auto">{{
          $t('comum.inativo')
        }}</Badge>
      </li>
    </ul>

    <SidePanel v-model:open="painel" :title="editando ? $t('setores.editar') : $t('setores.novo')">
      <form id="form-setor" class="flex flex-col gap-4" novalidate @submit.prevent="salvar">
        <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
        <TextField v-model="form.name" :label="$t('setores.nome')" required />
        <TextField v-model="form.code" :label="$t('setores.codigo')" />
        <SelectField v-model="form.parent" :label="$t('setores.acima')" :options="opcoesAcima" />
        <Checkbox v-if="editando" v-model="form.is_active" :label="$t('comum.ativo')" />
      </form>
      <template #actions>
        <Button variant="secondary" @click="painel = false">{{ $t('comum.cancelar') }}</Button>
        <Button
          type="submit"
          form="form-setor"
          :disabled="criar.isPending.value || editar.isPending.value || !form.name.trim()"
        >
          {{ $t('comum.salvar') }}
        </Button>
      </template>
    </SidePanel>
  </div>
</template>
