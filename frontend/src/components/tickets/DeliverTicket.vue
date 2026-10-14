<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Button from '@/components/ui/Button.vue'
import { type Chamado, chamadosApi, useAcaoNoChamado, useStatus } from '@/composables/chamados'
import { useToast } from '@/composables/useToast'

/**
 * Marcar como entregue: um clique muda o status para "Entregue" (ação set_status), sem tarefa nem
 * código de resolução. Sem um status com esse nome (renomeado ou removido), o botão não aparece.
 */
const props = defineProps<{ chamado: Chamado }>()
const { t } = useI18n()
const toast = useToast()
const status = useStatus()

const entregue = computed(() => status.data.value?.find((s) => s.name === 'Entregue'))

const numero = () => String(props.chamado.number)
const entregar = useAcaoNoChamado(numero, (status_id: number) =>
  chamadosApi.mudarStatusPara(numero(), status_id),
)

async function marcar() {
  try {
    await entregar.mutateAsync(entregue.value!.id)
    toast.show({ title: t('chamado.entregue.feito') })
  } catch (e) {
    toast.show({ title: (e as Error).message, variant: 'error' })
  }
}
</script>

<template>
  <Button
    v-if="entregue && chamado.status.id !== entregue.id"
    variant="gold"
    class="w-full"
    :disabled="entregar.isPending.value"
    @click="marcar"
  >
    {{ t('chamado.entregue.marcar') }}
  </Button>
</template>
