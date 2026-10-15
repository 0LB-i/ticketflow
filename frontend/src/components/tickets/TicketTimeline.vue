<script setup lang="ts">
import { Clock } from 'lucide-vue-next'
import { computed, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Pessoa } from '@/components/editor/MentionList.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import RichEditor from '@/components/editor/RichEditor.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import DateTimeField from '@/components/ui/DateTimeField.vue'
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
import type { Schemas } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

import AttachmentList from './AttachmentList.vue'

/**
 * Linha do tempo do chamado (docs/10 §10.6): o registro e as tarefas, pela data em que foram
 * feitas. O autor edita (texto, tempo gasto, data e hora) e remove a tarefa a qualquer momento.
 */
const props = defineProps<{
  chamado: Chamado
  comentarios: Comentario[]
  pessoas: Pessoa[]
}>()
const { t } = useI18n()
const auth = useAuthStore()

/** Anexos do registro (chave null) e de cada comentário, menos as imagens já no texto. */
const anexos = computed(() => {
  const de = (comentario: string | null, texto: string): Anexo[] => {
    const noTexto = new Set(anexosNoTexto(texto))
    return props.chamado.attachments.filter(
      (a) => a.comment_id === comentario && !noTexto.has(a.id),
    )
  }
  return new Map<string | null, Anexo[]>([
    [null, de(null, props.chamado.description)],
    ...props.comentarios.map((c) => [c.id, de(c.id, c.body)] as const),
  ])
})

const numero = () => String(props.chamado.number)
const editando = ref<string | null>(null)
const removendo = ref<string | null>(null)
const texto = ref('')
const tempo = ref('')
const minutos = computed(() => lerDuracao(tempo.value))
/** Data e hora da tarefa; `null` (botão Agora) é a hora atual. */
const feitaEm = ref<string | null>(null)
const erro = ref<string | null>(null)
const editor = useTemplateRef('editor')

const ehAutor = (c: Comentario) => c.author.id === auth.me?.id

function editar(c: Comentario) {
  editando.value = c.id
  removendo.value = null
  texto.value = c.body
  tempo.value = c.time_spent_minutes ? formatarHoraMinuto(c.time_spent_minutes) : ''
  feitaEm.value = c.done_at
  erro.value = null
}

const salvar = useAcaoNoChamado(numero, (a: { id: string; body: Schemas['CommentIn'] }) =>
  chamadosApi.editarComentario(numero(), a.id, a.body),
)
const remover = useAcaoNoChamado(numero, (id: string) =>
  chamadosApi.removerComentario(numero(), id),
)

async function salvarEdicao(id: string) {
  erro.value = null
  try {
    await salvar.mutateAsync({
      id,
      body: {
        body: texto.value,
        time_spent_minutes: minutos.value ?? null,
        done_at: feitaEm.value ?? new Date().toISOString(),
        mention_ids: editor.value?.[0]?.mencionados() ?? [],
        attachment_ids: anexosNoTexto(texto.value),
      },
    })
    editando.value = null
  } catch (e) {
    erro.value = (e as Error).message
  }
}

function pedirRemocao(id: string) {
  removendo.value = id
  erro.value = null
}

async function confirmarRemocao(id: string) {
  erro.value = null
  try {
    await remover.mutateAsync(id)
    removendo.value = null
  } catch (e) {
    erro.value = (e as Error).message
  }
}
</script>

<template>
  <ol class="flex flex-col gap-3" :aria-label="t('chamado.linhaDoTempo')">
    <li class="rounded-lg border border-border bg-surface p-4">
      <p class="text-muted">
        <span class="font-medium text-fg">{{ chamado.created_by.display_name }}</span>
        · {{ formatarDataHora(chamado.created_at) }}
      </p>
      <MarkdownView v-if="chamado.description" class="mt-2" :source="chamado.description" />
      <p v-else class="mt-2 text-muted italic">{{ t('chamado.semDescricao') }}</p>
      <AttachmentList v-if="anexos.get(null)?.length" class="mt-3" :anexos="anexos.get(null)!" />
    </li>

    <li v-for="c in comentarios" :key="c.id" class="rounded-lg border border-border bg-surface p-4">
      <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted">
        <span class="font-medium text-fg">{{ c.author.display_name }}</span>
        <span>· {{ formatarDataHora(c.done_at) }}</span>
        <span v-if="c.edited_at">· {{ t('chamado.editado') }}</span>
        <Badge v-if="c.is_solution" color="green">{{ t('chamado.solucao') }}</Badge>
        <Badge v-if="c.time_spent_minutes" color="gray">
          <Clock class="size-3.5" aria-hidden="true" />
          <span class="sr-only">{{ t('chamado.tempoGasto') }}:</span>
          <span class="tabular-nums">{{ formatarDuracao(c.time_spent_minutes) }}</span>
        </Badge>
        <div
          v-if="ehAutor(c) && editando !== c.id"
          class="ml-auto flex items-center gap-1"
          :role="removendo === c.id ? 'group' : undefined"
          :aria-label="removendo === c.id ? t('chamado.removerTarefaPergunta') : undefined"
        >
          <template v-if="removendo === c.id">
            <span class="text-fg">{{ t('chamado.removerTarefaPergunta') }}</span>
            <Button variant="secondary" size="sm" @click="removendo = null">
              {{ t('comum.cancelar') }}
            </Button>
            <Button
              variant="danger"
              size="sm"
              :disabled="remover.isPending.value"
              @click="confirmarRemocao(c.id)"
            >
              {{ t('chamado.removerTarefa') }}
            </Button>
          </template>
          <template v-else>
            <Button variant="ghost" size="sm" @click="editar(c)">
              {{ t('chamado.editarComentario') }}
            </Button>
            <Button variant="ghost" size="sm" @click="pedirRemocao(c.id)">
              {{ t('chamado.removerTarefa') }}
            </Button>
          </template>
        </div>
      </div>
      <p v-if="erro && removendo === c.id" class="mt-2 text-danger" role="alert">{{ erro }}</p>
      <div v-if="editando === c.id" class="mt-2 flex flex-col gap-2">
        <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
        <RichEditor
          ref="editor"
          v-model="texto"
          :label="t('chamado.editarComentario')"
          :pessoas="pessoas"
          anexar
        />
        <div class="flex flex-wrap items-start gap-4">
          <DurationField
            v-model="tempo"
            class="w-40"
            :label="t('chamado.tempoGasto')"
            :error="minutos === undefined ? t('chamado.tempoInvalido') : undefined"
          />
          <DateTimeField v-model="feitaEm" :label="t('chamado.feitaEm')" />
        </div>
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
        <AttachmentList v-if="anexos.get(c.id)?.length" class="mt-3" :anexos="anexos.get(c.id)!" />
      </template>
    </li>
  </ol>
</template>
