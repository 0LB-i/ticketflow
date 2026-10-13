<script setup lang="ts">
import { Clock } from 'lucide-vue-next'
import { computed, onBeforeUnmount, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Pessoa } from '@/components/editor/MentionList.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import RichEditor from '@/components/editor/RichEditor.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import TextField from '@/components/ui/TextField.vue'
import {
  type Chamado,
  chamadosApi,
  type Comentario,
  type Evento,
  useAcaoNoChamado,
} from '@/composables/chamados'
import { type Anexo, anexosNoTexto } from '@/composables/anexos'
import { formatarDataHora, formatarDuracao, lerDuracao } from '@/composables/formato'
import { useAuthStore } from '@/stores/auth'

import AttachmentList from './AttachmentList.vue'
import { descreverEvento } from './eventos'

/** Linha do tempo do chamado (docs/10 §10.6): registro, comentários e eventos em ordem. */
const props = defineProps<{
  chamado: Chamado
  comentarios: Comentario[]
  eventos: Evento[]
  pessoas: Pessoa[]
}>()
const { t } = useI18n()
const auth = useAuthStore()

type Item =
  | { tipo: 'comentario'; quando: string; comentario: Comentario }
  | { tipo: 'evento'; quando: string; evento: Evento }

const itens = computed<Item[]>(() =>
  [
    ...props.comentarios.map((c) => ({
      tipo: 'comentario' as const,
      quando: c.created_at,
      comentario: c,
    })),
    // O registro já aparece no topo, com a descrição.
    ...props.eventos
      .filter((e) => e.type !== 'ticket.created')
      .map((e) => ({ tipo: 'evento' as const, quando: e.created_at, evento: e })),
  ].sort((a, b) => a.quando.localeCompare(b.quando)),
)

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
  tempo.value = c.time_spent_minutes ? formatarDuracao(c.time_spent_minutes) : ''
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

    <template
      v-for="item in itens"
      :key="item.tipo === 'evento' ? `e${item.evento.id}` : item.comentario.id"
    >
      <li v-if="item.tipo === 'evento'" class="flex flex-wrap gap-x-2 px-4 text-muted">
        <span aria-hidden="true">◦</span>
        <span>{{ descreverEvento(item.evento, t) }}</span>
        <span>· {{ formatarDataHora(item.evento.created_at) }}</span>
      </li>
      <li v-else class="rounded-lg border border-border bg-surface p-4">
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted">
          <span class="font-medium text-fg">{{ item.comentario.author.full_name }}</span>
          <span>· {{ formatarDataHora(item.comentario.created_at) }}</span>
          <span v-if="item.comentario.edited_at">· {{ t('chamado.editado') }}</span>
          <Badge v-if="item.comentario.is_solution" color="green">{{ t('chamado.solucao') }}</Badge>
          <Badge v-if="item.comentario.time_spent_minutes" color="gray">
            <Clock class="size-3.5" aria-hidden="true" />
            <span class="sr-only">{{ t('chamado.tempoGasto') }}:</span>
            <span class="tabular-nums">{{
              formatarDuracao(item.comentario.time_spent_minutes)
            }}</span>
          </Badge>
          <Button
            v-if="podeEditar(item.comentario) && editando !== item.comentario.id"
            variant="ghost"
            size="sm"
            class="ml-auto"
            @click="editar(item.comentario)"
          >
            {{ t('chamado.editarComentario') }}
          </Button>
        </div>
        <div v-if="editando === item.comentario.id" class="mt-2 flex flex-col gap-2">
          <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
          <RichEditor
            ref="editor"
            v-model="texto"
            :label="t('chamado.editarComentario')"
            :pessoas="pessoas"
            anexar
          />
          <TextField
            v-model="tempo"
            class="max-w-56"
            :label="t('chamado.tempoGasto')"
            :hint="minutos === undefined ? undefined : t('chamado.tempoDica')"
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
              @click="salvarEdicao(item.comentario.id)"
            >
              {{ t('comum.salvar') }}
            </Button>
          </div>
        </div>
        <template v-else>
          <MarkdownView class="mt-2" :source="item.comentario.body" />
          <AttachmentList
            v-if="anexosDe(item.comentario.id, item.comentario.body).length"
            class="mt-3"
            :anexos="anexosDe(item.comentario.id, item.comentario.body)"
          />
        </template>
      </li>
    </template>
  </ol>
</template>
