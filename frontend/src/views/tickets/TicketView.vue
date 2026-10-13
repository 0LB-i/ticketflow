<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'

import CommentBox from '@/components/tickets/CommentBox.vue'
import TicketDetails from '@/components/tickets/TicketDetails.vue'
import TicketTimeline from '@/components/tickets/TicketTimeline.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import { useChamado, useComentarios, useEventos, usePessoas } from '@/composables/chamados'
import { formatarDataHora } from '@/composables/formato'

/** Detalhe do chamado (docs/10 §10.6). O que aparece depende de `allowed_actions`. */
const props = defineProps<{ numero: string }>()
const { t } = useI18n()
const chamado = useChamado(() => props.numero)
const comentarios = useComentarios(() => props.numero)
const eventos = useEventos(() => props.numero)
const pessoas = usePessoas()

const falha = computed(() => (chamado.error.value as { status?: number } | null)?.status)

watchEffect(() => {
  const c = chamado.data.value
  document.title = `${c ? `#${c.number} ${c.title}` : t('chamado.titulo')} · ${t('app.nome')}`
})
</script>

<template>
  <div class="mx-auto flex max-w-6xl flex-col gap-4">
    <p v-if="chamado.isPending.value" class="text-muted">{{ t('comum.carregando') }}</p>
    <div v-else-if="chamado.isError.value" class="flex flex-col gap-2">
      <h1 class="text-xl font-semibold">
        {{
          falha === 403
            ? t('chamado.semAcesso')
            : falha === 404
              ? t('chamado.naoEncontrado')
              : t('comum.erroInesperado')
        }}
      </h1>
      <RouterLink to="/chamados" class="text-primary underline">{{
        t('chamado.voltarParaLista')
      }}</RouterLink>
    </div>

    <template v-else-if="chamado.data.value">
      <header class="flex flex-col gap-2">
        <div class="flex flex-wrap items-center gap-2">
          <h1 class="min-w-0 text-xl font-semibold break-words">
            <span class="text-muted tabular-nums">#{{ chamado.data.value.number }}</span>
            {{ chamado.data.value.title }}
          </h1>
          <StatusBadge
            :kind="chamado.data.value.status.kind"
            :label="chamado.data.value.status.name"
          />
        </div>
        <p class="text-muted">
          {{
            t('chamado.registradoPor', {
              quando: formatarDataHora(chamado.data.value.created_at),
              quem: chamado.data.value.created_by.full_name,
            })
          }}
        </p>
      </header>

      <div class="grid items-start gap-4 lg:grid-cols-[1fr_20rem]">
        <div class="flex min-w-0 flex-col gap-4">
          <TicketTimeline
            :chamado="chamado.data.value"
            :comentarios="comentarios.data.value ?? []"
            :eventos="eventos.data.value ?? []"
            :pessoas="pessoas"
          />
          <CommentBox
            v-if="chamado.data.value.allowed_actions.includes('comment')"
            :chamado="chamado.data.value"
            :pessoas="pessoas"
          />
        </div>
        <TicketDetails :chamado="chamado.data.value" :pessoas="pessoas" />
      </div>
    </template>
  </div>
</template>
