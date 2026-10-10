<script setup lang="ts">
import { Trash2 } from 'lucide-vue-next'
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Checkbox from '@/components/ui/Checkbox.vue'
import DataTable from '@/components/ui/DataTable.vue'
import SelectField from '@/components/ui/SelectField.vue'
import SidePanel from '@/components/ui/SidePanel.vue'
import TextField from '@/components/ui/TextField.vue'
import { type Grupo, gruposApi, useAlteracao, useGrupos, useUsuarios } from '@/composables/admin'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

useHead('grupos.titulo')
const { t } = useI18n()
const toast = useToast()
const grupos = useGrupos()
const usuarios = useUsuarios()
const auth = useAuthStore()

/** Mudança nos próprios grupos: atualiza o usuário logado (grupos e permissões de supervisor). */
async function seForEu(usuario: string) {
  if (usuario === auth.me?.id) await auth.carregar()
}

const mostrarInativos = ref(false)
const lista = computed(() =>
  (grupos.data.value ?? []).filter((g) => mostrarInativos.value || g.is_active),
)
const avisos = computed(() =>
  (['queue_only', 'email_all_members'] as const).map((v) => ({
    value: v,
    label: t(`grupos.avisos.${v}`),
  })),
)
const funcoes = computed(() =>
  (['member', 'supervisor'] as const).map((v) => ({ value: v, label: t(`grupos.funcoes.${v}`) })),
)

const painel = ref(false)
const editandoId = ref<string | null>(null)
const editando = computed(() => grupos.data.value?.find((g) => g.id === editandoId.value) ?? null)
const form = reactive({
  name: '',
  description: '',
  notify_on_new: 'queue_only' as 'queue_only' | 'email_all_members',
  is_active: true,
})
const novoMembro = reactive({ usuario: undefined as string | undefined, role: 'member' as const })
const erro = ref<string | null>(null)

const candidatos = computed(() =>
  (usuarios.data.value ?? [])
    .filter(
      (u) => u.status !== 'inativo' && !editando.value?.members.some((m) => m.user_id === u.id),
    )
    .map((u) => ({ value: u.id, label: `${u.full_name} (${u.email})` })),
)

function abrir(g: Grupo | null) {
  editandoId.value = g?.id ?? null
  Object.assign(form, {
    name: g?.name ?? '',
    description: g?.description ?? '',
    notify_on_new: g?.notify_on_new ?? 'queue_only',
    is_active: g?.is_active ?? true,
  })
  Object.assign(novoMembro, { usuario: undefined, role: 'member' })
  erro.value = null
  painel.value = true
}

const criar = useAlteracao(gruposApi.criar, ['grupos'])
const editar = useAlteracao(
  async (a: Parameters<typeof gruposApi.editar>[0]) => {
    const grupo = await gruposApi.editar(a)
    // Nome ou situação de um grupo de que sou membro também muda os meus dados.
    if (grupo.members.some((m) => m.user_id === auth.me?.id)) await auth.carregar()
    return grupo
  },
  ['grupos'],
)
const definirMembro = useAlteracao(
  async (a: Parameters<typeof gruposApi.definirMembro>[0]) => {
    const grupo = await gruposApi.definirMembro(a)
    await seForEu(a.usuario)
    return grupo
  },
  ['grupos', 'usuarios'],
)
const removerMembro = useAlteracao(
  async (a: Parameters<typeof gruposApi.removerMembro>[0]) => {
    const grupo = await gruposApi.removerMembro(a)
    await seForEu(a.usuario)
    return grupo
  },
  ['grupos', 'usuarios'],
)

async function tentar(acao: () => Promise<unknown>) {
  erro.value = null
  try {
    await acao()
  } catch (e) {
    erro.value = (e as Error).message
  }
}

function salvar() {
  return tentar(async () => {
    const dados = { ...form, description: form.description.trim() || null }
    if (editando.value) {
      await editar.mutateAsync({ id: editando.value.id, ...dados })
      toast.show({ title: t('comum.salvo') })
      painel.value = false
    } else {
      // Criado, o painel continua aberto para incluir os membros.
      const criado = await criar.mutateAsync(dados)
      toast.show({ title: t('grupos.criado') })
      editandoId.value = criado.id
    }
  })
}

function adicionar() {
  const usuario = novoMembro.usuario
  if (!editando.value || !usuario) return
  return tentar(async () => {
    await definirMembro.mutateAsync({ grupo: editando.value!.id, usuario, role: novoMembro.role })
    novoMembro.usuario = undefined
  })
}
</script>

<template>
  <div class="mx-auto flex max-w-5xl flex-col gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="text-xl font-semibold">{{ $t('grupos.titulo') }}</h1>
      <Button @click="abrir(null)">{{ $t('grupos.novo') }}</Button>
    </div>
    <Checkbox v-model="mostrarInativos" :label="$t('comum.mostrarInativos')" />

    <p v-if="grupos.isPending.value" class="text-muted">{{ $t('comum.carregando') }}</p>
    <DataTable
      v-else
      :caption="$t('grupos.titulo')"
      row-key="id"
      :rows="lista"
      :columns="[
        { key: 'name', label: $t('grupos.nome') },
        { key: 'supervisores', label: $t('grupos.supervisores') },
        { key: 'quantidade', label: $t('grupos.membros') },
        { key: 'is_active', label: $t('grupos.situacao') },
      ]"
    >
      <template #cell-name="{ row }">
        <button type="button" class="font-medium text-primary underline" @click="abrir(row)">
          {{ row.name }}
        </button>
      </template>
      <template #cell-supervisores="{ row }">
        {{
          row.members
            .filter((m) => m.role === 'supervisor')
            .map((m) => m.full_name)
            .join(', ') || '—'
        }}
      </template>
      <template #cell-quantidade="{ row }">{{ row.members.length }}</template>
      <template #cell-is_active="{ row }">
        <Badge :color="row.is_active ? 'green' : 'gray'">
          {{ row.is_active ? $t('comum.ativo') : $t('comum.inativo') }}
        </Badge>
      </template>
    </DataTable>

    <SidePanel v-model:open="painel" :title="editando ? $t('grupos.editar') : $t('grupos.novo')">
      <div class="flex flex-col gap-6">
        <form id="form-grupo" class="flex flex-col gap-4" novalidate @submit.prevent="salvar">
          <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
          <TextField v-model="form.name" :label="$t('grupos.nome')" required />
          <TextField v-model="form.description" :label="$t('grupos.descricao')" />
          <SelectField v-model="form.notify_on_new" :label="$t('grupos.aviso')" :options="avisos" />
          <Checkbox v-if="editando" v-model="form.is_active" :label="$t('comum.ativo')" />
        </form>

        <section class="flex flex-col gap-3 border-t border-border pt-4" aria-labelledby="membros">
          <h3 id="membros" class="font-semibold">{{ $t('grupos.membros') }}</h3>
          <p v-if="!editando" class="text-muted">{{ $t('grupos.salveAntes') }}</p>
          <template v-else>
            <p v-if="!editando.members.length" class="text-muted">{{ $t('grupos.semMembros') }}</p>
            <ul class="flex flex-col divide-y divide-border">
              <li
                v-for="m in editando.members"
                :key="m.user_id"
                class="flex items-center gap-2 py-2"
              >
                <span class="min-w-0 flex-1">
                  <span class="block truncate font-medium">{{ m.full_name }}</span>
                  <span class="block truncate text-xs text-muted">{{ m.email }}</span>
                </span>
                <select
                  :value="m.role"
                  :aria-label="$t('grupos.funcao')"
                  class="h-8 rounded-md border border-border-input bg-surface px-2"
                  @change="
                    tentar(() =>
                      definirMembro.mutateAsync({
                        grupo: editando!.id,
                        usuario: m.user_id,
                        role: ($event.target as HTMLSelectElement).value as 'member' | 'supervisor',
                      }),
                    )
                  "
                >
                  <option v-for="f in funcoes" :key="f.value" :value="f.value">
                    {{ f.label }}
                  </option>
                </select>
                <Button
                  variant="ghost"
                  size="sm"
                  :aria-label="`${$t('comum.remover')} ${m.full_name}`"
                  @click="
                    tentar(() =>
                      removerMembro.mutateAsync({ grupo: editando!.id, usuario: m.user_id }),
                    )
                  "
                >
                  <Trash2 class="size-4" aria-hidden="true" />
                </Button>
              </li>
            </ul>
            <div class="flex flex-col gap-2 rounded-md bg-surface-raised p-3">
              <SelectField
                v-model="novoMembro.usuario"
                :label="$t('grupos.adicionarMembro')"
                :options="candidatos"
              />
              <SelectField
                v-model="novoMembro.role"
                :label="$t('grupos.funcao')"
                :options="funcoes"
              />
              <Button
                variant="secondary"
                :disabled="!novoMembro.usuario || definirMembro.isPending.value"
                @click="adicionar"
              >
                {{ $t('comum.adicionar') }}
              </Button>
            </div>
          </template>
        </section>
      </div>
      <template #actions>
        <Button variant="secondary" @click="painel = false">{{ $t('comum.fechar') }}</Button>
        <Button
          type="submit"
          form="form-grupo"
          :disabled="criar.isPending.value || editar.isPending.value || form.name.trim().length < 2"
        >
          {{ $t('comum.salvar') }}
        </Button>
      </template>
    </SidePanel>
  </div>
</template>
