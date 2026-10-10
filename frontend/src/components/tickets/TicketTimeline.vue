<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Pessoa } from '@/components/editor/MentionList.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import RichEditor from '@/components/editor/RichEditor.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import {
  type Chamado,
  chamadosApi,
  type Comentario,
  type Evento,
  useAcaoNoChamado,
} from '@/composables/chamados'
import { formatarDataHora } from '@/composables/formato'
import { useAuthStore } from '@/stores/auth'

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

const editando = ref<string | null>(null)
const texto = ref('')
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
  erro.value = null
}

const salvar = useAcaoNoChamado(
  () => String(props.chamado.number),
  (a: { id: string; body: string; mention_ids: string[] }) =>
    chamadosApi.editarComentario(String(props.chamado.number), a.id, {
      body: a.body,
      mention_ids: a.mention_ids,
    }),
)

async function salvarEdicao(id: string) {
  erro.value = null
  try {
    await salvar.mutateAsync({
      id,
      body: texto.value,
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
          />
          <div class="flex justify-end gap-2">
            <Button variant="secondary" size="sm" @click="editando = null">
              {{ t('comum.cancelar') }}
            </Button>
            <Button
              size="sm"
              :disabled="salvar.isPending.value || !texto.trim()"
              @click="salvarEdicao(item.comentario.id)"
            >
              {{ t('comum.salvar') }}
            </Button>
          </div>
        </div>
        <MarkdownView v-else class="mt-2" :source="item.comentario.body" />
      </li>
    </template>
  </ol>
</template>
