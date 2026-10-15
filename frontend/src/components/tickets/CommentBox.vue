<script setup lang="ts">
import { computed, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Pessoa } from '@/components/editor/MentionList.vue'
import RichEditor from '@/components/editor/RichEditor.vue'
import Button from '@/components/ui/Button.vue'
import DurationField from '@/components/ui/DurationField.vue'
import { anexosNoTexto } from '@/composables/anexos'
import { type Acao, type Chamado, chamadosApi, useAcaoNoChamado } from '@/composables/chamados'
import { lerDuracao } from '@/composables/formato'
import { useToast } from '@/composables/useToast'

import AttachmentUploader from './AttachmentUploader.vue'

/**
 * Adicionar uma tarefa (o andamento do chamado, um comentário na API) e, na mesma ação, mudar o
 * status (docs/10 §10.6). Em reabrir o texto é obrigatório (docs/10 §10.5). Cada tarefa pode
 * levar o tempo gasto nela. "Marcar como entregue" e "Cancelar chamado" ficam na lateral
 * (TicketDetails).
 */
const props = defineProps<{ chamado: Chamado; pessoas: Pessoa[] }>()
const { t } = useI18n()
const toast = useToast()
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

// Aguardar não aparece na tela (decisão de 2026-10-14); entregar e cancelar ficam na lateral.
const ACOES: { acao: Acao; exigeTexto: boolean }[] = [
  { acao: 'resume', exigeTexto: false },
  { acao: 'reopen', exigeTexto: true },
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
  return executar(
    () =>
      mudar.mutateAsync({
        action: acao,
        comment: texto.value,
        time_spent_minutes: minutos.value ?? null,
        attachment_ids: anexosDoEnvio(),
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
    <div class="flex items-start justify-between gap-3">
      <DurationField
        v-model="tempo"
        class="w-40"
        :label="t('chamado.tempoGasto')"
        :error="minutos === undefined ? t('chamado.tempoInvalido') : undefined"
      />
      <!-- mt-8: na altura do campo de tempo, abaixo do rótulo -->
      <AttachmentUploader ref="anexador" v-model="anexos" simples class="mt-8 min-w-0" />
    </div>
    <div class="flex flex-wrap gap-2">
      <Button type="submit" :disabled="ocupado || !texto.trim()">{{
        t('chamado.comentar')
      }}</Button>
      <Button
        v-for="a in disponiveis"
        :key="a.acao"
        variant="secondary"
        :disabled="ocupado"
        @click="pedir(a.acao, a.exigeTexto)"
      >
        {{ t(`chamado.acoes.${a.acao}`) }}
      </Button>
    </div>
  </form>
</template>
