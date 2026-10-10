<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Checkbox from '@/components/ui/Checkbox.vue'
import DataTable from '@/components/ui/DataTable.vue'
import LinkDialog from '@/components/ui/LinkDialog.vue'
import SelectField from '@/components/ui/SelectField.vue'
import SidePanel from '@/components/ui/SidePanel.vue'
import TextField from '@/components/ui/TextField.vue'
import {
  type LinkDeAcesso,
  type Usuario,
  useAlteracao,
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

const busca = ref('')
const mostrarInativos = ref(false)
const lista = computed(() =>
  (usuarios.data.value ?? []).filter(
    (u) =>
      (mostrarInativos.value || u.status !== 'inativo') &&
      `${u.full_name} ${u.email}`.toLowerCase().includes(busca.value.trim().toLowerCase()),
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
const form = reactive({ full_name: '', email: '', role: 'agent' as 'agent' | 'admin' | 'auditor' })
const erro = ref<string | null>(null)

function abrirNovo() {
  editando.value = null
  Object.assign(form, { full_name: '', email: '', role: 'agent' })
  erro.value = null
  painel.value = true
}

function abrirEdicao(u: Usuario) {
  editando.value = u
  Object.assign(form, { full_name: u.full_name, email: u.email, role: u.role })
  erro.value = null
  painel.value = true
}

// Link de acesso (convite ou redefinição) quando não há SMTP
const link = ref<{ aberto: boolean; nome: string; dados: LinkDeAcesso | null }>({
  aberto: false,
  nome: '',
  dados: null,
})

function mostrarLink(nome: string, email: string, dados: LinkDeAcesso) {
  if (dados.url) {
    link.value = { aberto: true, nome, dados }
  } else {
    toast.show({ title: t('usuarios.linkEnviado'), description: email })
  }
}

const criar = useAlteracao(usuariosApi.criar, ['usuarios'])
const editar = useAlteracao(usuariosApi.editar, ['usuarios', 'grupos'])
const enviarLink = useAlteracao(usuariosApi.enviarLink, ['usuarios'])

async function salvar() {
  erro.value = null
  try {
    if (editando.value) {
      await editar.mutateAsync({
        id: editando.value.id,
        full_name: form.full_name,
        role: form.role,
      })
      toast.show({ title: t('comum.salvo') })
    } else {
      const criado = await criar.mutateAsync({ ...form })
      toast.show({ title: t('usuarios.criado') })
      mostrarLink(criado.full_name, criado.email, criado.link)
    }
    painel.value = false
  } catch (e) {
    erro.value = (e as Error).message
  }
}

async function alternarAtivo() {
  if (!editando.value) return
  erro.value = null
  try {
    const ativo = editando.value.status === 'inativo'
    editando.value = await editar.mutateAsync({ id: editando.value.id, is_active: ativo })
  } catch (e) {
    erro.value = (e as Error).message
  }
}

async function enviarAcesso() {
  if (!editando.value) return
  erro.value = null
  try {
    const dados = await enviarLink.mutateAsync(editando.value.id)
    mostrarLink(editando.value.full_name, editando.value.email, dados)
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

    <div class="flex flex-wrap items-end gap-4">
      <div class="w-full max-w-xs">
        <TextField v-model="busca" :label="$t('comum.buscar')" type="search" />
      </div>
      <Checkbox v-model="mostrarInativos" :label="$t('comum.mostrarInativos')" class="pb-2" />
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
      :description="editando ? editando.email : undefined"
    >
      <form id="form-usuario" class="flex flex-col gap-4" novalidate @submit.prevent="salvar">
        <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
        <TextField v-model="form.full_name" :label="$t('usuarios.nome')" required />
        <TextField
          v-if="!editando"
          v-model="form.email"
          :label="$t('usuarios.email')"
          type="email"
          required
        />
        <SelectField v-model="form.role" :label="$t('usuarios.papel')" :options="papeis" />
        <p class="text-muted">{{ $t('usuarios.gruposAviso') }}</p>

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
          <template v-if="!ehVoceMesmo">
            <p v-if="editando.status !== 'inativo'" class="text-muted">
              {{ $t('usuarios.desativarAviso') }}
            </p>
            <Button
              :variant="editando.status === 'inativo' ? 'secondary' : 'danger'"
              :disabled="editar.isPending.value"
              @click="alternarAtivo"
            >
              {{ editando.status === 'inativo' ? $t('comum.reativar') : $t('comum.desativar') }}
            </Button>
          </template>
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
