<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import Button from '@/components/ui/Button.vue'
import DurationField from '@/components/ui/DurationField.vue'
import Modal from '@/components/ui/Modal.vue'
import SelectField from '@/components/ui/SelectField.vue'
import TextAreaField from '@/components/ui/TextAreaField.vue'
import {
  type Chamado,
  chamadosApi,
  useAcaoNoChamado,
  useCodigosDeResolucao,
} from '@/composables/chamados'
import { lerDuracao } from '@/composables/formato'
import { useToast } from '@/composables/useToast'

/**
 * Concluir o chamado (docs/10 §10.5): o que foi feito vira a última tarefa (com o tempo gasto,
 * se houver), marcada como solução, junto com o código de resolução.
 */
const props = defineProps<{ chamado: Chamado }>()
const { t } = useI18n()
const toast = useToast()
const codigos = useCodigosDeResolucao()

const aberto = ref(false)
const texto = ref('')
const tempo = ref('')
const minutos = computed(() => lerDuracao(tempo.value))
const codigo = ref('')
const erro = ref<string | null>(null)
const opcoesCodigo = computed(() =>
  (codigos.data.value ?? [])
    .filter((c) => c.is_active)
    .map((c) => ({ value: String(c.id), label: c.name })),
)

const numero = () => String(props.chamado.number)
const concluir = useAcaoNoChamado(
  numero,
  (body: { comment: string; time_spent_minutes: number | null; resolution_code_id: number }) =>
    chamadosApi.mudarStatus(numero(), { action: 'close', attachment_ids: [], ...body }),
)

function abrir() {
  texto.value = ''
  tempo.value = ''
  codigo.value = ''
  erro.value = null
  aberto.value = true
}

async function confirmar() {
  erro.value = null
  try {
    await concluir.mutateAsync({
      comment: texto.value,
      time_spent_minutes: minutos.value ?? null,
      resolution_code_id: Number(codigo.value),
    })
    aberto.value = false
    toast.show({ title: t('chamado.feito.close') })
  } catch (e) {
    erro.value = (e as Error).message
  }
}
</script>

<template>
  <Button variant="gold" class="w-full" @click="abrir">{{ t('chamado.acoes.close') }}</Button>
  <Modal
    v-model:open="aberto"
    :title="t('chamado.confirmar.close')"
    :description="t('chamado.confirmarTexto.close')"
  >
    <div class="flex flex-col gap-4">
      <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
      <TextAreaField v-model="texto" :label="t('chamado.oQueFoiFeito')" required />
      <DurationField
        v-model="tempo"
        class="w-40"
        :label="t('chamado.tempoGasto')"
        :error="minutos === undefined ? t('chamado.tempoInvalido') : undefined"
      />
      <SelectField
        v-model="codigo"
        :label="t('chamado.codigoResolucao')"
        :options="opcoesCodigo"
        required
      />
    </div>
    <template #actions>
      <Button variant="secondary" @click="aberto = false">{{ t('comum.cancelar') }}</Button>
      <Button
        variant="gold"
        :disabled="concluir.isPending.value || !texto.trim() || !codigo || minutos === undefined"
        @click="confirmar"
      >
        {{ t('chamado.acoes.close') }}
      </Button>
    </template>
  </Modal>
</template>
