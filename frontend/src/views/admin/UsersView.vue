<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Checkbox from '@/components/ui/Checkbox.vue'
import DataTable from '@/components/ui/DataTable.vue'
import LinkDialog from '@/components/ui/LinkDialog.vue'
import Modal from '@/components/ui/Modal.vue'
import SelectField from '@/components/ui/SelectField.vue'
import SidePanel from '@/components/ui/SidePanel.vue'
import TextField from '@/components/ui/TextField.vue'
import {
  type LinkDeAcesso,
  type Usuario,
  useAlteracao,
  useGrupos,
  useUsuarios,
  usuariosApi,
} from '@/composables/admin'
import { formatarDataHora } from '@/composables/formato'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

useHead('usuarios.titulo')
const { t } = useI18n()
const toast = useToast()
const auth = useAuthStore()
const usuarios = useUsuarios()
const grupos = useGrupos()
const gruposAtivos = computed(() => (grupos.data.value ?? []).filter((g) => g.is_active))

const busca = ref('')
const lista = computed(() =>
  (usuarios.data.value ?? []).filter((u) =>
    `${u.full_name} ${u.email ?? ''} ${u.username ?? ''}`
      .toLowerCase()
      .includes(busca.value.trim().toLowerCase()),
  ),
)

const papeis = computed(() =>
  (['agent', 'admin', 'auditor'] as const).map((p) => ({
    value: p,
    label: t(`usuarios.papeis.${p}`),
  })),
)
const corStatus = { ativo: 'green', convite_pendente: 'teal', inativo: 'gray' } as const

// Painel de criação/edição
const painel = ref(false)
const editando = ref<Usuario | null>(null)
const form = reactive({
  full_name: '',
  email: '',
  role: 'agent' as 'agent' | 'admin' | 'auditor',
  password: '',
  team_ids: [] as string[],
})
const erro = ref<string | null>(null)

function abrirNovo() {
  editando.value = null
  Object.assign(form, { full_name: '', email: '', role: 'agent', password: '', team_ids: [] })
  erro.value = null
  painel.value = true
}

function abrirEdicao(u: Usuario) {
  editando.value = u
  Object.assign(form, { full_name: u.full_name, email: u.email ?? '', role: u.role, password: '' })
  erro.value = null
  painel.value = true
}

// Link de acesso (convite ou redefinição) quando não há SMTP
const link = ref<{ aberto: boolean; nome: string; dados: LinkDeAcesso | null }>({
  aberto: false,
  nome: '',
  dados: null,
})

function noGrupo(id: string, marcado: boolean) {
  form.team_ids = marcado ? [...form.team_ids, id] : form.team_ids.filter((g) => g !== id)
}

function mostrarLink(nome: string, email: string, dados: LinkDeAcesso) {
  if (dados.url) {
    link.value = { aberto: true, nome, dados }
  } else {
    toast.show({ title: t('usuarios.linkEnviado'), description: email })
  }
}

const criar = useAlteracao(usuariosApi.criar, ['usuarios', 'grupos'])
const editar = useAlteracao(usuariosApi.editar, ['usuarios', 'grupos'])
const enviarLink = useAlteracao(usuariosApi.enviarLink, ['usuarios'])
const excluir = useAlteracao(usuariosApi.excluir, ['usuarios', 'grupos'])

async function salvar() {
  erro.value = null
  try {
    if (editando.value) {
      const email = form.email.trim()
      await editar.mutateAsync({
        id: editando.value.id,
        full_name: form.full_name,
        role: form.role,
        ...(email && email !== editando.value.email ? { email } : {}),
      })
      toast.show({ title: t('comum.salvo') })
    } else {
      await criar.mutateAsync({ ...form })
      toast.show({ title: t('usuarios.criado') })
    }
    painel.value = false
  } catch (e) {
    erro.value = (e as Error).message
  }
}

// Quem foi desativado antes de existir a exclusão ainda pode ser reativado.
async function reativar() {
  if (!editando.value) return
  erro.value = null
  try {
    editando.value = await editar.mutateAsync({ id: editando.value.id, is_active: true })
  } catch (e) {
    erro.value = (e as Error).message
  }
}

const confirmarExclusao = ref(false)

async function excluirUsuario() {
  if (!editando.value) return
  confirmarExclusao.value = false
  erro.value = null
  try {
    await excluir.mutateAsync(editando.value.id)
    toast.show({ title: t('usuarios.excluido'), description: editando.value.full_name })
    painel.value = false
  } catch (e) {
    erro.value = (e as Error).message
  }
}

async function enviarAcesso() {
  if (!editando.value) return
  erro.value = null
  try {
    const dados = await enviarLink.mutateAsync(editando.value.id)
    mostrarLink(editando.value.full_name, editando.value.email ?? '', dados)
  } catch (e) {
    erro.value = (e as Error).message
  }
}

const ehVoceMesmo = computed(() => editando.value?.id === auth.me?.id)
</script>

<template>
  <div class="mx-auto flex max-w-6xl flex-col gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="text-xl font-semibold">{{ $t('usuarios.titulo') }}</h1>
      <Button @click="abrirNovo">{{ $t('usuarios.novo') }}</Button>
    </div>

    <div class="w-full max-w-xs">
      <TextField v-model="busca" :label="$t('comum.buscar')" type="search" />
    </div>

    <p v-if="usuarios.isPending.value" class="text-muted">{{ $t('comum.carregando') }}</p>
    <p v-else-if="usuarios.isError.value" class="text-danger">
      {{ usuarios.error.value?.message }}
    </p>
    <DataTable
      v-else
      :caption="$t('usuarios.titulo')"
      row-key="id"
      :rows="lista"
      :columns="[
        { key: 'full_name', label: $t('usuarios.nome') },
        { key: 'email', label: $t('usuarios.email') },
        { key: 'role', label: $t('usuarios.papel') },
        { key: 'teams', label: $t('usuarios.grupos') },
        { key: 'status', label: $t('usuarios.situacao') },
        { key: 'last_login_at', label: $t('usuarios.ultimoAcesso') },
      ]"
    >
      <template #cell-full_name="{ row }">
        <button type="button" class="font-medium text-primary underline" @click="abrirEdicao(row)">
          {{ row.full_name }}
        </button>
      </template>
      <template #cell-email="{ row }">
        <span v-if="row.email">{{ row.email }}</span>
        <span v-else class="text-muted">
          {{ $t('usuarios.usuarioLogin', { usuario: row.username }) }}
        </span>
      </template>
      <template #cell-role="{ row }">{{ $t(`usuarios.papeis.${row.role}`) }}</template>
      <template #cell-teams="{ row }">
        <span v-if="row.teams.length">{{ row.teams.map((g) => g.name).join(', ') }}</span>
        <span v-else-if="row.role !== 'auditor'" class="text-muted">{{
          $t('usuarios.semGrupo')
        }}</span>
      </template>
      <template #cell-status="{ row }">
        <Badge :color="corStatus[row.status]">{{ $t(`usuarios.status.${row.status}`) }}</Badge>
      </template>
      <template #cell-last_login_at="{ row }">
        {{ formatarDataHora(row.last_login_at) ?? $t('comum.nunca') }}
      </template>
    </DataTable>

    <SidePanel
      v-model:open="painel"
      :title="editando ? $t('usuarios.editar') : $t('usuarios.novo')"
      :description="
        editando
          ? (editando.email ?? $t('usuarios.usuarioLogin', { usuario: editando.username }))
          : undefined
      "
    >
      <form id="form-usuario" class="flex flex-col gap-4" novalidate @submit.prevent="salvar">
        <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
        <TextField v-model="form.full_name" :label="$t('usuarios.nome')" required />
        <TextField
          v-model="form.email"
          :label="$t('usuarios.email')"
          :hint="editando && !editando.email ? $t('usuarios.semEmail') : undefined"
          type="email"
          :required="!editando"
        />
        <TextField
          v-if="!editando"
          v-model="form.password"
          :label="$t('usuarios.senhaInicial')"
          :hint="$t('usuarios.senhaInicialDica')"
          autocomplete="off"
          required
        />
        <SelectField v-model="form.role" :label="$t('usuarios.papel')" :options="papeis" />
        <fieldset v-if="!editando" class="flex flex-col gap-2">
          <legend class="mb-1 font-medium">{{ $t('usuarios.membroDosGrupos') }}</legend>
          <Checkbox
            v-for="g in gruposAtivos"
            :key="g.id"
            :model-value="form.team_ids.includes(g.id)"
            :label="g.name"
            @update:model-value="noGrupo(g.id, $event)"
          />
          <p v-if="!gruposAtivos.length" class="text-muted">{{ $t('usuarios.semGrupos') }}</p>
        </fieldset>
        <p v-else class="text-muted">{{ $t('usuarios.gruposAviso') }}</p>

        <div v-if="editando" class="flex flex-col gap-3 border-t border-border pt-4">
          <p>
            <Badge :color="corStatus[editando.status]">
              {{ $t(`usuarios.status.${editando.status}`) }}
            </Badge>
          </p>
          <Button
            v-if="editando.status !== 'inativo'"
            variant="secondary"
            :disabled="enviarLink.isPending.value"
            @click="enviarAcesso"
          >
            {{
              editando.status === 'convite_pendente'
                ? $t('usuarios.enviarConvite')
                : $t('usuarios.enviarRedefinicao')
            }}
          </Button>
          <Button
            v-if="editando.status === 'inativo'"
            variant="secondary"
            :disabled="editar.isPending.value"
            @click="reativar"
          >
            {{ $t('comum.reativar') }}
          </Button>
          <Button
            v-if="!ehVoceMesmo"
            variant="danger"
            :disabled="excluir.isPending.value"
            @click="confirmarExclusao = true"
          >
            {{ $t('usuarios.excluir') }}
          </Button>
        </div>
      </form>
      <template #actions>
        <Button variant="secondary" @click="painel = false">{{ $t('comum.cancelar') }}</Button>
        <Button
          type="submit"
          form="form-usuario"
          :disabled="
            criar.isPending.value || editar.isPending.value || form.full_name.trim().length < 2
          "
        >
          {{ $t('comum.salvar') }}
        </Button>
      </template>
    </SidePanel>

    <Modal
      v-model:open="confirmarExclusao"
      :title="$t('usuarios.excluirTitulo', { nome: editando?.full_name })"
      :description="$t('usuarios.excluirAviso')"
    >
      <template #actions>
        <Button variant="secondary" @click="confirmarExclusao = false">
          {{ $t('comum.cancelar') }}
        </Button>
        <Button variant="danger" @click="excluirUsuario">{{ $t('usuarios.excluir') }}</Button>
      </template>
    </Modal>

    <LinkDialog
      v-if="link.dados?.url"
      v-model:open="link.aberto"
      :title="$t('usuarios.linkTitulo', { nome: link.nome })"
      :description="
        link.dados.purpose === 'invite'
          ? $t('usuarios.linkTextoConvite')
          : $t('usuarios.linkTextoRedefinir')
      "
      :url="link.dados.url"
    />
  </div>
</template>
