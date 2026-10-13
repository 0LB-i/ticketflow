<script setup lang="ts">
import { Clock } from 'lucide-vue-next'
import { computed, onBeforeUnmount, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Pessoa } from '@/components/editor/MentionList.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import RichEditor from '@/components/editor/RichEditor.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import DurationField from '@/components/ui/DurationField.vue'
import {
  type Chamado,
  chamadosApi,
  type Comentario,
  useAcaoNoChamado,
} from '@/composables/chamados'
import { type Anexo, anexosNoTexto } from '@/composables/anexos'
import {
  formatarDataHora,
  formatarDuracao,
  formatarHoraMinuto,
  lerDuracao,
} from '@/composables/formato'
import { useAuthStore } from '@/stores/auth'

import AttachmentList from './AttachmentList.vue'

/** Linha do tempo do chamado (docs/10 §10.6): o registro e os comentários (andamentos) em ordem. */
const props = defineProps<{
  chamado: Chamado
  comentarios: Comentario[]
  pessoas: Pessoa[]
}>()
const { t } = useI18n()
const auth = useAuthStore()

/** Anexos do registro (comentario = null) ou de um comentário, menos as imagens já no texto. */
function anexosDe(comentario: string | null, texto: string): Anexo[] {
  const noTexto = new Set(anexosNoTexto(texto))
  return props.chamado.attachments.filter((a) => a.comment_id === comentario && !noTexto.has(a.id))
}

const editando = ref<string | null>(null)
const texto = ref('')
const tempo = ref('')
const minutos = computed(() => lerDuracao(tempo.value))
const erro = ref<string | null>(null)
const editor = useTemplateRef('editor')
const agora = ref(Date.now())
// O botão "Editar" some quando acaba o prazo de edição, sem precisar recarregar a página.
const relogio = setInterval(() => (agora.value = Date.now()), 30_000)
onBeforeUnmount(() => clearInterval(relogio))

function podeEditar(c: Comentario) {
  return c.author.id === auth.me?.id && new Date(c.editable_until).getTime() > agora.value
}

function editar(c: Comentario) {
  agora.value = Date.now()
  editando.value = c.id
  texto.value = c.body
  tempo.value = c.time_spent_minutes ? formatarHoraMinuto(c.time_spent_minutes) : ''
  erro.value = null
}

const salvar = useAcaoNoChamado(
  () => String(props.chamado.number),
  (a: { id: string; body: string; time_spent_minutes: number | null; mention_ids: string[] }) =>
    chamadosApi.editarComentario(String(props.chamado.number), a.id, {
      body: a.body,
      time_spent_minutes: a.time_spent_minutes,
      mention_ids: a.mention_ids,
      attachment_ids: anexosNoTexto(a.body),
    }),
)

async function salvarEdicao(id: string) {
  erro.value = null
  try {
    await salvar.mutateAsync({
      id,
      body: texto.value,
      time_spent_minutes: minutos.value ?? null,
      mention_ids: editor.value?.[0]?.mencionados() ?? [],
    })
    editando.value = null
  } catch (e) {
    erro.value = (e as Error).message
  }
}
</script>

<template>
  <ol class="flex flex-col gap-3" :aria-label="t('chamado.linhaDoTempo')">
    <li class="rounded-lg border border-border bg-surface p-4">
      <p class="text-muted">
        <span class="font-medium text-fg">{{ chamado.created_by.full_name }}</span>
        · {{ formatarDataHora(chamado.created_at) }}
      </p>
      <MarkdownView v-if="chamado.description" class="mt-2" :source="chamado.description" />
      <p v-else class="mt-2 text-muted italic">{{ t('chamado.semDescricao') }}</p>
      <AttachmentList
        v-if="anexosDe(null, chamado.description).length"
        class="mt-3"
        :anexos="anexosDe(null, chamado.description)"
      />
    </li>

    <li v-for="c in comentarios" :key="c.id" class="rounded-lg border border-border bg-surface p-4">
      <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted">
        <span class="font-medium text-fg">{{ c.author.full_name }}</span>
        <span>· {{ formatarDataHora(c.created_at) }}</span>
        <span v-if="c.edited_at">· {{ t('chamado.editado') }}</span>
        <Badge v-if="c.is_solution" color="green">{{ t('chamado.solucao') }}</Badge>
        <Badge v-if="c.time_spent_minutes" color="gray">
          <Clock class="size-3.5" aria-hidden="true" />
          <span class="sr-only">{{ t('chamado.tempoGasto') }}:</span>
          <span class="tabular-nums">{{ formatarDuracao(c.time_spent_minutes) }}</span>
        </Badge>
        <Button
          v-if="podeEditar(c) && editando !== c.id"
          variant="ghost"
          size="sm"
          class="ml-auto"
          @click="editar(c)"
        >
          {{ t('chamado.editarComentario') }}
        </Button>
      </div>
      <div v-if="editando === c.id" class="mt-2 flex flex-col gap-2">
        <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
        <RichEditor
          ref="editor"
          v-model="texto"
          :label="t('chamado.editarComentario')"
          :pessoas="pessoas"
          anexar
        />
        <DurationField
          v-model="tempo"
          class="max-w-40"
          :label="t('chamado.tempoGasto')"
          :error="minutos === undefined ? t('chamado.tempoInvalido') : undefined"
        />
        <div class="flex justify-end gap-2">
          <Button variant="secondary" size="sm" @click="editando = null">
            {{ t('comum.cancelar') }}
          </Button>
          <Button
            size="sm"
            :disabled="
              salvar.isPending.value ||
              !texto.trim() ||
              minutos === undefined ||
              editor?.[0]?.enviando
            "
            @click="salvarEdicao(c.id)"
          >
            {{ t('comum.salvar') }}
          </Button>
        </div>
      </div>
      <template v-else>
        <MarkdownView class="mt-2" :source="c.body" />
        <AttachmentList
          v-if="anexosDe(c.id, c.body).length"
          class="mt-3"
          :anexos="anexosDe(c.id, c.body)"
        />
      </template>
    </li>
  </ol>
</template>
