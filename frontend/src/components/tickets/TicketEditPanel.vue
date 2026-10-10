<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import RichEditor from '@/components/editor/RichEditor.vue'
import Button from '@/components/ui/Button.vue'
import RadioGroup from '@/components/ui/RadioGroup.vue'
import SelectField from '@/components/ui/SelectField.vue'
import SidePanel from '@/components/ui/SidePanel.vue'
import TextField from '@/components/ui/TextField.vue'
import { type Schemas } from '@/api/client'
import { useSetores } from '@/composables/admin'
import {
  caminhoDasCategorias,
  type Chamado,
  chamadosApi,
  type TipoChamado,
  useAcaoNoChamado,
  useCategorias,
} from '@/composables/chamados'
import { useToast } from '@/composables/useToast'

/** Alterar campos e prioridade (docs/08 §8.5). Só vai para a API o que mudou. */
const props = defineProps<{ chamado: Chamado }>()
const open = defineModel<boolean>('open', { default: false })
const { t } = useI18n()
const toast = useToast()
const categorias = useCategorias()
const setores = useSetores()
const NENHUM = '__nenhum__'
const MATRIZ = 'matriz'

const pode = computed(() => new Set(props.chamado.allowed_actions))
const form = reactive({
  title: '',
  description: '',
  category: '',
  type: 'incident' as TipoChamado,
  department: NENHUM,
  beneficiary: '',
  urgency: '1',
  impact: '1',
  priority: MATRIZ,
  reason: '',
})
const erro = ref<string | null>(null)

watch(open, (aberto) => {
  if (!aberto) return
  const c = props.chamado
  Object.assign(form, {
    title: c.title,
    description: c.description,
    category: c.category.id,
    type: c.type,
    department: c.department?.id ?? NENHUM,
    beneficiary: c.beneficiary_name ?? '',
    urgency: String(c.urgency),
    impact: String(c.impact),
    priority: c.priority_overridden ? String(c.priority) : MATRIZ,
    reason: '',
  })
  erro.value = null
})

const caminhos = computed(() => caminhoDasCategorias(categorias.data.value ?? []))
const opcoesCategoria = computed(() =>
  (categorias.data.value ?? [])
    .filter((c) => c.is_active || c.id === props.chamado.category.id)
    .map((c) => ({ value: c.id, label: caminhos.value.get(c.id) ?? c.name }))
    .sort((a, b) => a.label.localeCompare(b.label, 'pt-BR')),
)
const opcoesSetor = computed(() => [
  { value: NENHUM, label: t('comum.nenhum') },
  ...(setores.data.value ?? [])
    .filter((s) => s.is_active || s.id === props.chamado.department?.id)
    .map((s) => ({ value: s.id, label: s.name })),
])
const opcoesTipo = computed(() =>
  (['incident', 'request', 'task'] as const).map((v) => ({ value: v, label: t(`tipos.${v}`) })),
)
const opcoesPrioridade = computed(() => [
  { value: MATRIZ, label: t('editarChamado.pelaMatriz') },
  ...[1, 2, 3, 4].map((n) => ({ value: String(n), label: t(`prioridade.${n}`) })),
])
const niveis = (chave: string) =>
  ['1', '2', '3'].map((n) => ({ value: n, label: t(`${chave}.${n}`) }))

/** Forçar uma prioridade (ou trocar a forçada) exige o motivo (docs/10 §10.3). */
const forcando = computed(
  () =>
    form.priority !== MATRIZ &&
    (!props.chamado.priority_overridden || form.priority !== String(props.chamado.priority)),
)

function mudancas(): Schemas['TicketUpdate'] {
  const c = props.chamado
  const m: Schemas['TicketUpdate'] = {}
  if (pode.value.has('edit')) {
    if (form.title.trim() !== c.title) m.title = form.title
    if (form.description !== c.description) m.description = form.description
    if (form.category !== c.category.id) m.category_id = form.category
    if (form.type !== c.type) m.type = form.type
    const dept = form.department === NENHUM ? null : form.department
    if (dept !== (c.department?.id ?? null)) m.department_id = dept
    const pessoa = form.beneficiary.trim() || null
    if (pessoa !== c.beneficiary_name) m.beneficiary_name = pessoa
  }
  if (pode.value.has('set_priority')) {
    if (Number(form.urgency) !== c.urgency) m.urgency = Number(form.urgency)
    if (Number(form.impact) !== c.impact) m.impact = Number(form.impact)
    if (forcando.value) {
      m.priority = Number(form.priority)
      m.priority_reason = form.reason
    } else if (form.priority === MATRIZ && c.priority_overridden) {
      m.priority = null
    }
  }
  return m
}

const salvar = useAcaoNoChamado(
  () => String(props.chamado.number),
  (body: Schemas['TicketUpdate']) => chamadosApi.editar(String(props.chamado.number), body),
)

async function enviar() {
  erro.value = null
  if (forcando.value && !form.reason.trim()) {
    erro.value = t('editarChamado.motivoObrigatorio')
    return
  }
  const m = mudancas()
  try {
    if (Object.keys(m).length) {
      await salvar.mutateAsync(m)
      toast.show({ title: t('comum.salvo') })
    }
    open.value = false
  } catch (e) {
    erro.value = (e as Error).message
  }
}
</script>

<template>
  <SidePanel v-model:open="open" :title="t('editarChamado.titulo', { numero: chamado.number })">
    <form id="form-editar-chamado" class="flex flex-col gap-4" novalidate @submit.prevent="enviar">
      <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
      <template v-if="pode.has('edit')">
        <TextField v-model="form.title" :label="t('novoChamado.tituloCampo')" required />
        <RichEditor v-model="form.description" :label="t('novoChamado.descricao')" />
        <SelectField
          v-model="form.category"
          :label="t('novoChamado.categoria')"
          :options="opcoesCategoria"
        />
        <SelectField v-model="form.type" :label="t('chamado.tipo')" :options="opcoesTipo" />
        <SelectField v-model="form.department" :label="t('chamado.setor')" :options="opcoesSetor" />
        <TextField v-model="form.beneficiary" :label="t('chamado.pessoa')" />
      </template>
      <template v-if="pode.has('set_priority')">
        <RadioGroup
          v-model="form.urgency"
          :legend="t('chamado.urgencia')"
          :options="niveis('urgencia')"
        />
        <RadioGroup
          v-model="form.impact"
          :legend="t('chamado.impacto')"
          :options="niveis('impacto')"
        />
        <SelectField
          v-model="form.priority"
          :label="t('chamado.prioridade')"
          :options="opcoesPrioridade"
        />
        <TextField
          v-if="forcando"
          v-model="form.reason"
          :label="t('editarChamado.motivo')"
          :hint="t('editarChamado.motivoDica')"
          required
        />
      </template>
    </form>
    <template #actions>
      <Button variant="secondary" @click="open = false">{{ t('comum.cancelar') }}</Button>
      <Button type="submit" form="form-editar-chamado" :disabled="salvar.isPending.value">
        {{ t('comum.salvar') }}
      </Button>
    </template>
  </SidePanel>
</template>
