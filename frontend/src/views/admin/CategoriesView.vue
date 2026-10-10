<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Checkbox from '@/components/ui/Checkbox.vue'
import SelectField from '@/components/ui/SelectField.vue'
import SidePanel from '@/components/ui/SidePanel.vue'
import TextField from '@/components/ui/TextField.vue'
import { categoriasApi, useAlteracao, useGrupos } from '@/composables/admin'
import { type Categoria, type TipoChamado, useCategorias } from '@/composables/chamados'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'

useHead('categorias.titulo')
const { t } = useI18n()
const toast = useToast()
const categorias = useCategorias()
const grupos = useGrupos()
const NENHUM = '__nenhum__' // o Select não aceita valor vazio
const MAX_NIVEIS = 3 // docs/08 §8.1
const TIPOS: TipoChamado[] = ['incident', 'request', 'task']

const mostrarInativas = ref(false)
const nomeDoGrupo = computed(
  () => new Map((grupos.data.value ?? []).map((g) => [g.id, g.name] as const)),
)

/** Nível de cada categoria na árvore (1 na raiz). */
const niveis = computed(() => {
  const todas = new Map((categorias.data.value ?? []).map((c) => [c.id, c]))
  const nivel = (c: Categoria): number => {
    const pai = c.parent_id ? todas.get(c.parent_id) : undefined
    return pai ? nivel(pai) + 1 : 1
  }
  return new Map([...todas.values()].map((c) => [c.id, nivel(c)]))
})

/** Árvore achatada na ordem de exibição. */
const arvore = computed(() => {
  const todas = (categorias.data.value ?? []).filter((c) => mostrarInativas.value || c.is_active)
  const filhos = new Map<string | null, Categoria[]>()
  for (const c of todas) {
    const pai = todas.some((p) => p.id === c.parent_id) ? c.parent_id : null
    filhos.set(pai, [...(filhos.get(pai) ?? []), c])
  }
  const linhas: { categoria: Categoria; nivel: number }[] = []
  const visitar = (pai: string | null, nivel: number) => {
    for (const c of filhos.get(pai) ?? []) {
      linhas.push({ categoria: c, nivel })
      visitar(c.id, nivel + 1)
    }
  }
  visitar(null, 0)
  return linhas
})

const painel = ref(false)
const editando = ref<Categoria | null>(null)
const form = reactive({
  name: '',
  description: '',
  parent: NENHUM,
  team: NENHUM,
  type: 'incident' as TipoChamado,
  is_confidential: false,
  is_active: true,
})
const erro = ref<string | null>(null)

/** "Categoria acima": nem a própria, nem as de baixo dela, nem as do último nível. */
const opcoesAcima = computed(() => {
  const todas = categorias.data.value ?? []
  const bloqueadas = new Set<string>()
  if (editando.value) {
    bloqueadas.add(editando.value.id)
    let mudou = true
    while (mudou) {
      mudou = false
      for (const c of todas) {
        if (c.parent_id && bloqueadas.has(c.parent_id) && !bloqueadas.has(c.id)) {
          bloqueadas.add(c.id)
          mudou = true
        }
      }
    }
  }
  return [
    { value: NENHUM, label: t('categorias.nenhumaAcima') },
    ...todas
      .filter(
        (c) => c.is_active && !bloqueadas.has(c.id) && (niveis.value.get(c.id) ?? 1) < MAX_NIVEIS,
      )
      .map((c) => ({ value: c.id, label: c.name })),
  ]
})

const opcoesGrupo = computed(() => [
  { value: NENHUM, label: t('categorias.semGrupoPadrao') },
  ...(grupos.data.value ?? [])
    .filter((g) => g.is_active)
    .map((g) => ({ value: g.id, label: g.name })),
])
const opcoesTipo = computed(() => TIPOS.map((tipo) => ({ value: tipo, label: t(`tipos.${tipo}`) })))

function abrir(c: Categoria | null) {
  editando.value = c
  Object.assign(form, {
    name: c?.name ?? '',
    description: c?.description ?? '',
    parent: c?.parent_id ?? NENHUM,
    team: c?.default_team_id ?? NENHUM,
    type: c?.default_type ?? 'incident',
    is_confidential: c?.is_confidential ?? false,
    is_active: c?.is_active ?? true,
  })
  erro.value = null
  painel.value = true
}

const criar = useAlteracao(categoriasApi.criar, ['categorias'])
const editar = useAlteracao(categoriasApi.editar, ['categorias'])

async function salvar() {
  erro.value = null
  const dados = {
    name: form.name,
    description: form.description.trim() || null,
    parent_id: form.parent === NENHUM ? null : form.parent,
    default_team_id: form.team === NENHUM ? null : form.team,
    default_type: form.type,
    is_confidential: form.is_confidential,
  }
  try {
    if (editando.value) {
      await editar.mutateAsync({ id: editando.value.id, ...dados, is_active: form.is_active })
      toast.show({ title: t('comum.salvo') })
    } else {
      await criar.mutateAsync(dados)
      toast.show({ title: t('categorias.criada') })
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
        <h1 class="text-xl font-semibold">{{ $t('categorias.titulo') }}</h1>
        <p class="mt-1 text-muted">{{ $t('categorias.descricao') }}</p>
      </div>
      <Button @click="abrir(null)">{{ $t('categorias.nova') }}</Button>
    </div>
    <Checkbox v-model="mostrarInativas" :label="$t('categorias.mostrarInativas')" />

    <p v-if="categorias.isPending.value" class="text-muted">{{ $t('comum.carregando') }}</p>
    <p v-else-if="!arvore.length" class="text-muted">{{ $t('categorias.vazio') }}</p>
    <ul
      v-else
      class="divide-y divide-border rounded-lg border border-border bg-surface"
      role="tree"
    >
      <li
        v-for="{ categoria, nivel } in arvore"
        :key="categoria.id"
        role="treeitem"
        :aria-level="nivel + 1"
        class="flex flex-wrap items-center gap-2 py-2 pr-3"
        :style="{ paddingLeft: `${0.75 + nivel * 1.5}rem` }"
      >
        <span v-if="nivel" class="text-muted" aria-hidden="true">↳</span>
        <button type="button" class="font-medium text-primary underline" @click="abrir(categoria)">
          {{ categoria.name }}
        </button>
        <span v-if="categoria.default_team_id" class="text-muted">
          → {{ nomeDoGrupo.get(categoria.default_team_id) }}
        </span>
        <span class="ml-auto flex gap-1">
          <Badge v-if="categoria.is_confidential" color="red">{{
            $t('categorias.confidencial')
          }}</Badge>
          <Badge color="gray">{{ $t(`tipos.${categoria.default_type}`) }}</Badge>
          <Badge v-if="!categoria.is_active" color="gray">{{ $t('comum.inativo') }}</Badge>
        </span>
      </li>
    </ul>

    <SidePanel
      v-model:open="painel"
      :title="editando ? $t('categorias.editar') : $t('categorias.nova')"
    >
      <form id="form-categoria" class="flex flex-col gap-4" novalidate @submit.prevent="salvar">
        <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
        <TextField v-model="form.name" :label="$t('categorias.nome')" required />
        <TextField
          v-model="form.description"
          :label="$t('categorias.descricaoCampo')"
          :hint="$t('categorias.descricaoDica')"
        />
        <SelectField v-model="form.parent" :label="$t('categorias.acima')" :options="opcoesAcima" />
        <SelectField
          v-model="form.team"
          :label="$t('categorias.grupoPadrao')"
          :options="opcoesGrupo"
        />
        <SelectField
          v-model="form.type"
          :label="$t('categorias.tipoPadrao')"
          :options="opcoesTipo"
        />
        <div class="flex flex-col gap-1">
          <Checkbox v-model="form.is_confidential" :label="$t('categorias.confidencial')" />
          <p class="text-muted">{{ $t('categorias.confidencialDica') }}</p>
        </div>
        <Checkbox v-if="editando" v-model="form.is_active" :label="$t('comum.ativo')" />
      </form>
      <template #actions>
        <Button variant="secondary" @click="painel = false">{{ $t('comum.cancelar') }}</Button>
        <Button
          type="submit"
          form="form-categoria"
          :disabled="criar.isPending.value || editar.isPending.value || !form.name.trim()"
        >
          {{ $t('comum.salvar') }}
        </Button>
      </template>
    </SidePanel>
  </div>
</template>
