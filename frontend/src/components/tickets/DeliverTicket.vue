<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Button from '@/components/ui/Button.vue'
import { type Chamado, chamadosApi, useAcaoNoChamado, useStatus } from '@/composables/chamados'
import { useToast } from '@/composables/useToast'

/**
 * Marcar como entregue: um clique leva o chamado ao status padrão do comportamento Entregue
 * (`delivered`, a revisão do supervisor), sem tarefa nem código de resolução. Daí, só o
 * supervisor ou o admin conclui.
 */
const props = defineProps<{ chamado: Chamado }>()
const { t } = useI18n()
const toast = useToast()
const status = useStatus()

const entregue = computed(() =>
  status.data.value?.find((s) => s.kind === 'delivered' && s.is_default),
)

// Já entregue, concluído ou cancelado: o botão não aparece.
const SEM_BOTAO = ['delivered', 'closed', 'canceled']
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
    v-if="entregue && !SEM_BOTAO.includes(chamado.status.kind)"
    variant="gold"
    class="w-full"
    :disabled="entregar.isPending.value"
    @click="marcar"
  >
    {{ t('chamado.entregue.marcar') }}
  </Button>
</template>
