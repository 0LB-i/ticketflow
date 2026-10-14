<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'
import { type Chamado, chamadosApi, useAcaoNoChamado, useStatus } from '@/composables/chamados'
import { useToast } from '@/composables/useToast'

/**
 * Marcar como entregue: só muda o status para "Entregue" (ação set_status), sem tarefa nem
 * código de resolução. Sem um status com esse nome (renomeado ou removido), o botão não aparece.
 */
const props = defineProps<{ chamado: Chamado }>()
const { t } = useI18n()
const toast = useToast()
const status = useStatus()

const entregue = computed(() => status.data.value?.find((s) => s.name === 'Entregue'))
const aberto = ref(false)
const erro = ref<string | null>(null)

const numero = () => String(props.chamado.number)
const entregar = useAcaoNoChamado(numero, (status_id: number) =>
  chamadosApi.mudarStatusPara(numero(), status_id),
)

function abrir() {
  erro.value = null
  aberto.value = true
}

async function confirmar() {
  erro.value = null
  try {
    await entregar.mutateAsync(entregue.value!.id)
    aberto.value = false
    toast.show({ title: t('chamado.entregue.feito') })
  } catch (e) {
    erro.value = (e as Error).message
  }
}
</script>

<template>
  <template v-if="entregue && chamado.status.id !== entregue.id">
    <Button variant="gold" class="w-full" @click="abrir">
      {{ t('chamado.entregue.marcar') }}
    </Button>
    <Modal
      v-model:open="aberto"
      :title="t('chamado.entregue.titulo')"
      :description="t('chamado.entregue.texto')"
    >
      <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
      <template #actions>
        <Button variant="secondary" @click="aberto = false">{{ t('comum.cancelar') }}</Button>
        <Button variant="gold" :disabled="entregar.isPending.value" @click="confirmar">
          {{ t('chamado.entregue.marcar') }}
        </Button>
      </template>
    </Modal>
  </template>
</template>
