<script setup lang="ts">
import { computed, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Pessoa } from '@/components/editor/MentionList.vue'
import RichEditor from '@/components/editor/RichEditor.vue'
import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'
import SelectField from '@/components/ui/SelectField.vue'
import {
  type Acao,
  type Chamado,
  chamadosApi,
  useAcaoNoChamado,
  useCodigosDeResolucao,
} from '@/composables/chamados'
import { useToast } from '@/composables/useToast'

/**
 * Comentar e, na mesma ação, mudar o status (docs/10 §10.6). O texto da caixa vai como
 * comentário; em aguardar, concluir, reabrir e cancelar ele é obrigatório (docs/10 §10.5).
 */
const props = defineProps<{ chamado: Chamado; pessoas: Pessoa[] }>()
const { t } = useI18n()
const toast = useToast()
const codigos = useCodigosDeResolucao()
const editor = useTemplateRef('editor')

const texto = ref('')
const erro = ref<string | null>(null)
const numero = () => String(props.chamado.number)
const acoes = computed(() => new Set(props.chamado.allowed_actions))

const ACOES: { acao: Acao; exigeTexto: boolean; variante: 'secondary' | 'danger' }[] = [
  { acao: 'wait', exigeTexto: true, variante: 'secondary' },
  { acao: 'resume', exigeTexto: false, variante: 'secondary' },
  { acao: 'close', exigeTexto: true, variante: 'secondary' },
  { acao: 'reopen', exigeTexto: true, variante: 'secondary' },
  { acao: 'cancel', exigeTexto: true, variante: 'danger' },
]
const disponiveis = computed(() => ACOES.filter((a) => acoes.value.has(a.acao)))

const comentar = useAcaoNoChamado(numero, (body: { body: string; mention_ids: string[] }) =>
  chamadosApi.comentar(numero(), body),
)
const mudar = useAcaoNoChamado(
  numero,
  (body: { action: Acao; comment: string; resolution_code_id?: number }) =>
    chamadosApi.mudarStatus(numero(), body),
)
const ocupado = computed(() => comentar.isPending.value || mudar.isPending.value)

async function executar(fn: () => Promise<unknown>, aviso: string) {
  erro.value = null
  try {
    await fn()
    texto.value = ''
    toast.show({ title: aviso })
  } catch (e) {
    erro.value = (e as Error).message
  }
}

function enviarComentario() {
  if (!texto.value.trim()) return
  return executar(
    () =>
      comentar.mutateAsync({ body: texto.value, mention_ids: editor.value?.mencionados() ?? [] }),
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
    />
    <div class="flex flex-wrap gap-2">
      <Button type="submit" :disabled="ocupado || !texto.trim()">{{
        t('chamado.comentar')
      }}</Button>
      <Button
        v-for="a in disponiveis"
        :key="a.acao"
        :variant="a.variante"
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
          :variant="confirmando === 'cancel' ? 'danger' : 'primary'"
          :disabled="ocupado || (confirmando === 'close' && !codigo)"
          @click="confirmando && mudarStatus(confirmando)"
        >
          {{ confirmando ? t(`chamado.acoes.${confirmando}`) : '' }}
        </Button>
      </template>
    </Modal>
  </form>
</template>
