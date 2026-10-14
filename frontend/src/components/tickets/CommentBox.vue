<script setup lang="ts">
import { computed, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Pessoa } from '@/components/editor/MentionList.vue'
import RichEditor from '@/components/editor/RichEditor.vue'
import Button from '@/components/ui/Button.vue'
import DurationField from '@/components/ui/DurationField.vue'
import Modal from '@/components/ui/Modal.vue'
import SelectField from '@/components/ui/SelectField.vue'
import { anexosNoTexto } from '@/composables/anexos'
import {
  type Acao,
  type Chamado,
  chamadosApi,
  useAcaoNoChamado,
  useCodigosDeResolucao,
} from '@/composables/chamados'
import { lerDuracao } from '@/composables/formato'
import { useToast } from '@/composables/useToast'

import AttachmentUploader from './AttachmentUploader.vue'

/**
 * Adicionar uma tarefa (o andamento do chamado, um comentário na API) e, na mesma ação, mudar o
 * status (docs/10 §10.6). Em concluir, reabrir e cancelar o texto é obrigatório (docs/10 §10.5).
 * Cada tarefa pode levar o tempo gasto nela.
 */
const props = defineProps<{ chamado: Chamado; pessoas: Pessoa[] }>()
const { t } = useI18n()
const toast = useToast()
const codigos = useCodigosDeResolucao()
const editor = useTemplateRef<InstanceType<typeof RichEditor>>('editor')
const anexador = useTemplateRef<InstanceType<typeof AttachmentUploader>>('anexador')
const anexos = ref<string[]>([])
/** Os arquivos do "Anexar" e as imagens coladas no texto. */
const anexosDoEnvio = () => [...new Set([...anexos.value, ...anexosNoTexto(texto.value)])]

const texto = ref('')
const tempo = ref('')
const minutos = computed(() => lerDuracao(tempo.value))
const erro = ref<string | null>(null)
const numero = () => String(props.chamado.number)
const acoes = computed(() => new Set(props.chamado.allowed_actions))

// Concluir fica por último, à direita. Aguardar não aparece na tela (decisão de 2026-10-14).
const ACOES: { acao: Acao; exigeTexto: boolean; variante: 'secondary' | 'danger' | 'gold' }[] = [
  { acao: 'resume', exigeTexto: false, variante: 'secondary' },
  { acao: 'reopen', exigeTexto: true, variante: 'secondary' },
  { acao: 'cancel', exigeTexto: true, variante: 'danger' },
  { acao: 'close', exigeTexto: true, variante: 'gold' },
]
const disponiveis = computed(() => ACOES.filter((a) => acoes.value.has(a.acao)))

const comentar = useAcaoNoChamado(
  numero,
  (body: {
    body: string
    time_spent_minutes: number | null
    mention_ids: string[]
    attachment_ids: string[]
  }) => chamadosApi.comentar(numero(), body),
)
const mudar = useAcaoNoChamado(
  numero,
  (body: {
    action: Acao
    comment: string
    time_spent_minutes: number | null
    resolution_code_id?: number
    attachment_ids: string[]
  }) => chamadosApi.mudarStatus(numero(), body),
)
const ocupado = computed<boolean>(
  () =>
    comentar.isPending.value ||
    mudar.isPending.value ||
    !!editor.value?.enviando ||
    !!anexador.value?.enviando ||
    minutos.value === undefined,
)

async function executar(fn: () => Promise<unknown>, aviso: string) {
  erro.value = null
  try {
    await fn()
    texto.value = ''
    tempo.value = ''
    anexador.value?.limpar()
    toast.show({ title: aviso })
  } catch (e) {
    erro.value = (e as Error).message
  }
}

function enviarComentario() {
  if (!texto.value.trim() || minutos.value === undefined) return
  return executar(
    () =>
      comentar.mutateAsync({
        body: texto.value,
        time_spent_minutes: minutos.value ?? null,
        mention_ids: editor.value?.mencionados() ?? [],
        attachment_ids: anexosDoEnvio(),
      }),
    t('chamado.comentado'),
  )
}

// Concluir e cancelar passam por uma confirmação (concluir pede o código de resolução).
const confirmando = ref<Acao | null>(null)
const codigo = ref('')
const opcoesCodigo = computed(() =>
  (codigos.data.value ?? [])
    .filter((c) => c.is_active)
    .map((c) => ({ value: String(c.id), label: c.name })),
)

function pedir(acao: Acao, exigeTexto: boolean) {
  erro.value = null
  if (exigeTexto && !texto.value.trim()) {
    erro.value = t(`chamado.textoObrigatorio.${acao}`)
    return
  }
  if (minutos.value && !texto.value.trim()) {
    erro.value = t('chamado.tempoSemTexto')
    return
  }
  if (acao === 'close' || acao === 'cancel') {
    codigo.value = ''
    confirmando.value = acao
    return
  }
  return mudarStatus(acao)
}

function mudarStatus(acao: Acao) {
  confirmando.value = null
  return executar(
    () =>
      mudar.mutateAsync({
        action: acao,
        comment: texto.value,
        time_spent_minutes: minutos.value ?? null,
        attachment_ids: anexosDoEnvio(),
        ...(acao === 'close' ? { resolution_code_id: Number(codigo.value) } : {}),
      }),
    t(`chamado.feito.${acao}`),
  )
}
</script>

<template>
  <form
    class="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4"
    @submit.prevent="enviarComentario"
  >
    <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
    <RichEditor
      ref="editor"
      v-model="texto"
      :label="t('chamado.novoComentario')"
      :placeholder="t('chamado.comentarioDica')"
      :pessoas="pessoas"
      anexar
    />
    <div class="flex flex-wrap items-start gap-3">
      <DurationField
        v-model="tempo"
        class="w-40"
        :label="t('chamado.tempoGasto')"
        :error="minutos === undefined ? t('chamado.tempoInvalido') : undefined"
      />
      <!-- mt-7: alinhado ao campo de tempo, abaixo do rótulo -->
      <AttachmentUploader ref="anexador" v-model="anexos" class="mt-7 min-w-64 flex-1" />
    </div>
    <div class="flex flex-wrap gap-2">
      <Button type="submit" :disabled="ocupado || !texto.trim()">{{
        t('chamado.comentar')
      }}</Button>
      <Button
        v-for="a in disponiveis"
        :key="a.acao"
        :variant="a.variante"
        :class="a.acao === 'close' ? 'ml-auto' : undefined"
        :disabled="ocupado"
        @click="pedir(a.acao, a.exigeTexto)"
      >
        {{ t(`chamado.acoes.${a.acao}`) }}
      </Button>
    </div>

    <Modal
      :open="confirmando !== null"
      :title="confirmando ? t(`chamado.confirmar.${confirmando}`) : ''"
      :description="confirmando ? t(`chamado.confirmarTexto.${confirmando}`) : ''"
      @update:open="(aberto) => !aberto && (confirmando = null)"
    >
      <SelectField
        v-if="confirmando === 'close'"
        v-model="codigo"
        :label="t('chamado.codigoResolucao')"
        :options="opcoesCodigo"
        required
      />
      <template #actions>
        <Button variant="secondary" @click="confirmando = null">{{ t('comum.cancelar') }}</Button>
        <Button
          :variant="confirmando === 'cancel' ? 'danger' : 'gold'"
          :disabled="ocupado || (confirmando === 'close' && !codigo)"
          @click="confirmando && mudarStatus(confirmando)"
        >
          {{ confirmando ? t(`chamado.acoes.${confirmando}`) : '' }}
        </Button>
      </template>
    </Modal>
  </form>
</template>
