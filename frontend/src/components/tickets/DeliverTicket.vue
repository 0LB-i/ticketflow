<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Button from '@/components/ui/Button.vue'
import { type Chamado, chamadosApi, useAcaoNoChamado, useStatus } from '@/composables/chamados'
import { useToast } from '@/composables/useToast'

/**
 * Marcar como entregue: um clique leva o chamado ao status de revisão do supervisor ("Entregue",
 * `is_review`), sem tarefa nem código de resolução. Daí, só o supervisor ou o admin conclui.
 * O status é achado pela marca de revisão, não pelo nome; sem ele, o botão não aparece.
 */
const props = defineProps<{ chamado: Chamado }>()
const { t } = useI18n()
const toast = useToast()
const status = useStatus()

const entregue = computed(() => status.data.value?.find((s) => s.is_review))

// Concluído ou cancelado não volta para a revisão por aqui.
const FINAIS = ['closed', 'canceled']
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
    v-if="entregue && chamado.status.id !== entregue.id && !FINAIS.includes(chamado.status.kind)"
    variant="gold"
    class="w-full"
    :disabled="entregar.isPending.value"
    @click="marcar"
  >
    {{ t('chamado.entregue.marcar') }}
  </Button>
</template>
