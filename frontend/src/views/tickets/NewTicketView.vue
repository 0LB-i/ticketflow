<script setup lang="ts">
import { compararTexto } from '@/i18n'
import { X } from 'lucide-vue-next'
import { computed, reactive, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import RichEditor from '@/components/editor/RichEditor.vue'
import Button from '@/components/ui/Button.vue'
import RadioGroup from '@/components/ui/RadioGroup.vue'
import SelectField from '@/components/ui/SelectField.vue'
import TextField from '@/components/ui/TextField.vue'
import { useGrupos, useSetores } from '@/composables/admin'
import {
  caminhoDasCategorias,
  chamadosApi,
  useAcaoNoChamado,
  useCategorias,
  usePessoas,
} from '@/composables/chamados'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

/** Registro de chamado (docs/10 §10.4). */
useHead('novoChamado.titulo')
const { t } = useI18n()
const router = useRouter()
const toast = useToast()
const auth = useAuthStore()
const categorias = useCategorias()
const grupos = useGrupos()
const setores = useSetores()
const pessoas = usePessoas()
const editor = useTemplateRef('editor')
const NENHUM = '__nenhum__'

const meusGrupos = computed(() => auth.me?.teams ?? [])
const form = reactive({
  team: meusGrupos.value.length === 1 ? meusGrupos.value[0]!.id : '',
  category: '',
  title: '',
  description: '',
  department: NENHUM,
  beneficiary: '',
  urgency: '1',
  impact: '1',
  responsavel: 'me' as 'me' | 'fila' | 'outro',
  outro: '',
  observadores: [] as string[],
})
const erro = ref<string | null>(null)
const tentou = ref(false)

const caminhos = computed(() => caminhoDasCategorias(categorias.data.value ?? []))
const idsMeusGrupos = computed(() => new Set(meusGrupos.value.map((g) => g.id)))

/** Categorias ativas do grupo escolhido (ou sem grupo padrão), pelo caminho na árvore. */
const opcoesCategoria = computed(() =>
  (categorias.data.value ?? [])
    .filter(
      (c) =>
        c.is_active &&
        (!c.default_team_id ||
          (form.team
            ? c.default_team_id === form.team
            : idsMeusGrupos.value.has(c.default_team_id))),
    )
    .map((c) => ({ value: c.id, label: caminhos.value.get(c.id) ?? c.name }))
    .sort((a, b) => compararTexto(a.label, b.label)),
)

// Roteamento: escolher a categoria preenche o grupo padrão dela, se for um dos meus.
watch(
  () => form.category,
  (id) => {
    const categoria = categorias.data.value?.find((c) => c.id === id)
    if (
      !form.team &&
      categoria?.default_team_id &&
      idsMeusGrupos.value.has(categoria.default_team_id)
    )
      form.team = categoria.default_team_id
  },
)
watch(
  () => form.team,
  () => {
    if (!opcoesCategoria.value.some((o) => o.value === form.category)) form.category = ''
    form.outro = ''
  },
)

const supervisorDoGrupo = computed(
  () =>
    auth.me?.role === 'admin' ||
    meusGrupos.value.some((g) => g.id === form.team && g.role === 'supervisor'),
)
const membrosDoGrupo = computed(() =>
  (grupos.data.value?.find((g) => g.id === form.team)?.members ?? [])
    .filter((m) => m.is_active && m.user_id !== auth.me?.id)
    .map((m) => ({ value: m.user_id, label: m.full_name })),
)
const opcoesResponsavel = computed(() => [
  { value: 'me', label: t('novoChamado.eu') },
  { value: 'fila', label: t('novoChamado.fila') },
  ...(supervisorDoGrupo.value ? [{ value: 'outro', label: t('novoChamado.outro') }] : []),
])
const opcoesSetor = computed(() => [
  { value: NENHUM, label: t('comum.nenhum') },
  ...(setores.data.value ?? [])
    .filter((s) => s.is_active)
    .map((s) => ({ value: s.id, label: s.name })),
])
const niveis = (chave: string) =>
  ['1', '2', '3'].map((n) => ({ value: n, label: t(`${chave}.${n}`) }))

const nomes = computed(() => new Map(pessoas.value.map((p) => [p.id, p.label])))
const opcoesObservador = computed(() =>
  pessoas.value
    .filter((p) => p.id !== auth.me?.id && !form.observadores.includes(p.id))
    .map((p) => ({ value: p.id, label: p.label })),
)
const novoObservador = ref('')
watch(novoObservador, (id) => {
  if (id) {
    form.observadores.push(id)
    novoObservador.value = ''
  }
})

const faltando = computed(() => ({
  team: !form.team,
  category: !form.category,
  title: form.title.trim().length < 3,
  outro: form.responsavel === 'outro' && !form.outro,
}))

const registrar = useAcaoNoChamado('novo', chamadosApi.registrar)

async function enviar() {
  tentou.value = true
  erro.value = null
  if (Object.values(faltando.value).some(Boolean)) return
  try {
    const chamado = await registrar.mutateAsync({
      title: form.title,
      description: form.description,
      team_id: form.team,
      category_id: form.category,
      department_id: form.department === NENHUM ? null : form.department,
      beneficiary_name: form.beneficiary.trim() || null,
      urgency: Number(form.urgency),
      impact: Number(form.impact),
      assignee: form.responsavel === 'me' ? 'me' : form.responsavel === 'outro' ? form.outro : null,
      watcher_ids: form.observadores,
      mention_ids: editor.value?.mencionados() ?? [],
    })
    toast.show({
      title: t('novoChamado.registrado', { numero: chamado.number }),
      description: chamado.title,
    })
    await router.push(`/chamados/${chamado.number}`)
  } catch (e) {
    erro.value = (e as Error).message
  }
}
</script>

<template>
  <div class="mx-auto flex max-w-3xl flex-col gap-4">
    <h1 class="text-xl font-semibold">{{ $t('novoChamado.titulo') }}</h1>
    <p v-if="!meusGrupos.length" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">
      {{ $t('novoChamado.semGrupo') }}
    </p>

    <form
      v-else
      class="flex flex-col gap-5 rounded-lg border border-border bg-surface p-4 md:p-6"
      novalidate
      @submit.prevent="enviar"
    >
      <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>

      <div class="grid gap-4 md:grid-cols-2">
        <SelectField
          v-model="form.team"
          :label="$t('novoChamado.grupo')"
          :options="meusGrupos.map((g) => ({ value: g.id, label: g.name }))"
          :error="tentou && faltando.team ? $t('novoChamado.escolhaGrupo') : undefined"
          required
        />
        <SelectField
          v-model="form.category"
          :label="$t('novoChamado.categoria')"
          :options="opcoesCategoria"
          :error="tentou && faltando.category ? $t('novoChamado.escolhaCategoria') : undefined"
          required
        />
      </div>

      <TextField
        v-model="form.title"
        :label="$t('novoChamado.tituloCampo')"
        :hint="$t('novoChamado.tituloDica')"
        :error="tentou && faltando.title ? $t('novoChamado.tituloCurto') : undefined"
        required
      />
      <RichEditor
        ref="editor"
        v-model="form.description"
        :label="$t('novoChamado.descricao')"
        :placeholder="$t('novoChamado.descricaoDica')"
        :pessoas="pessoas"
      />

      <fieldset class="grid gap-4 md:grid-cols-2">
        <legend class="mb-2 font-medium">{{ $t('novoChamado.paraQuem') }}</legend>
        <SelectField
          v-model="form.department"
          :label="$t('chamado.setor')"
          :options="opcoesSetor"
        />
        <TextField
          v-model="form.beneficiary"
          :label="$t('chamado.pessoa')"
          :hint="$t('novoChamado.pessoaDica')"
        />
      </fieldset>

      <RadioGroup
        v-model="form.urgency"
        :legend="$t('chamado.urgencia')"
        :options="niveis('urgencia')"
      />
      <RadioGroup
        v-model="form.impact"
        :legend="$t('chamado.impacto')"
        :options="niveis('impacto')"
      />

      <div class="flex flex-col gap-3">
        <RadioGroup
          v-model="form.responsavel"
          :legend="$t('chamado.responsavel')"
          :options="opcoesResponsavel"
        />
        <div v-if="form.responsavel === 'outro'" class="max-w-sm">
          <SelectField
            v-model="form.outro"
            :label="$t('novoChamado.qualMembro')"
            :options="membrosDoGrupo"
            :error="tentou && faltando.outro ? $t('novoChamado.escolhaMembro') : undefined"
            required
          />
        </div>
      </div>

      <div class="flex flex-col gap-2">
        <div class="max-w-sm">
          <SelectField
            v-model="novoObservador"
            :label="$t('chamado.observadores')"
            :placeholder="$t('chamado.adicionarColega')"
            :options="opcoesObservador"
          />
        </div>
        <ul v-if="form.observadores.length" class="flex flex-wrap gap-2">
          <li
            v-for="id in form.observadores"
            :key="id"
            class="inline-flex items-center gap-1 rounded-full bg-surface-raised py-0.5 pr-1 pl-3"
          >
            {{ nomes.get(id) }}
            <button
              type="button"
              class="rounded-full p-0.5 text-muted hover:bg-border"
              :aria-label="$t('chamado.removerObservador', { nome: nomes.get(id) })"
              @click="form.observadores = form.observadores.filter((o) => o !== id)"
            >
              <X class="size-4" aria-hidden="true" />
            </button>
          </li>
        </ul>
      </div>

      <div class="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" @click="router.push('/chamados')">
          {{ $t('comum.cancelar') }}
        </Button>
        <Button type="submit" :disabled="registrar.isPending.value">
          {{ $t('novoChamado.registrar') }}
        </Button>
      </div>
    </form>
  </div>
</template>
