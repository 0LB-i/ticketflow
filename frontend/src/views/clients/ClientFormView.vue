<script setup lang="ts">
import { Plus, Trash2 } from 'lucide-vue-next'
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Checkbox from '@/components/ui/Checkbox.vue'
import RadioGroup from '@/components/ui/RadioGroup.vue'
import SelectField from '@/components/ui/SelectField.vue'
import TextAreaField from '@/components/ui/TextAreaField.vue'
import TextField from '@/components/ui/TextField.vue'
import { useAlteracao } from '@/composables/admin'
import {
  type Cliente,
  type ClienteEntrada,
  clientesApi,
  type TipoCliente,
  useCliente,
} from '@/composables/clientes'
import {
  cnpjValido,
  cpfValido,
  formatarCep,
  formatarDocumento,
  formatarTelefone,
  soDigitos,
  telefoneValido,
  UFS,
} from '@/composables/documentos'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

/**
 * Cadastro e edição de cliente, em três colunas (dados, contato, endereço) para caber na tela
 * do computador sem rolar. Só CEP, cidade e UF são obrigatórios; telefones e e-mails são listas
 * em que se adiciona e remove. Sem client.manage, o formulário só mostra os dados.
 */
const props = defineProps<{ id?: string }>()
const { t } = useI18n()
const router = useRouter()
const toast = useToast()
const auth = useAuthStore()
useHead(props.id ? 'clientes.editar' : 'clientes.novo')

const cliente = useCliente(() => props.id ?? null)
const podeEditar = computed(() => auth.pode('client.manage'))

const vazio = {
  kind: 'person' as TipoCliente,
  name: '',
  trade_name: '',
  document: '',
  id_number: '',
  birth_date: '',
  state_registration: '',
  municipal_registration: '',
  contact_name: '',
  postal_code: '',
  street: '',
  number: '',
  complement: '',
  district: '',
  city: '',
  state: '',
  notes: '',
  is_active: true,
}
const form = reactive({ ...vazio, phones: [''], emails: [''] })
const tentou = ref(false)
const erro = ref<string | null>(null)

function preencher(c: Cliente) {
  Object.assign(form, {
    ...Object.fromEntries(Object.keys(vazio).map((k) => [k, c[k as keyof Cliente] ?? ''])),
    is_active: c.is_active,
    document: formatarDocumento(c.document ?? '', c.kind),
    phones: c.phones.length ? c.phones.map(formatarTelefone) : [''],
    emails: c.emails.length ? [...c.emails] : [''],
    postal_code: formatarCep(c.postal_code),
  })
}
watch(
  () => cliente.data.value,
  (c) => c && preencher(c),
  { immediate: true },
)

// Máscaras enquanto se digita.
watch(
  () => [form.document, form.kind] as const,
  ([valor, tipo]) => (form.document = formatarDocumento(valor, tipo)),
)
watch(
  () => form.id_number,
  (v) => (form.id_number = soDigitos(v).slice(0, 14)),
)
watch(
  () => form.postal_code,
  (v) => (form.postal_code = formatarCep(v)),
)

const pf = computed(() => form.kind === 'person')
const opcoesTipo = computed(() =>
  (['person', 'company'] as const).map((k) => ({
    value: k,
    label: t(`clientes.tiposLongos.${k}`),
  })),
)
const opcoesUf = UFS.map((uf) => ({ value: uf, label: uf }))

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const erros = computed(() => {
  const e: Partial<Record<keyof typeof vazio, string>> = {}
  // PF: nome completo e CPF; PJ: razão social, nome fantasia e CNPJ.
  if (!form.name.trim()) e.name = t('clientes.erros.obrigatorio')
  if (!pf.value && !form.trade_name.trim()) e.trade_name = t('clientes.erros.obrigatorio')
  if (!form.document.trim()) e.document = t('clientes.erros.obrigatorio')
  else if (!(pf.value ? cpfValido(form.document) : cnpjValido(form.document)))
    e.document = t(pf.value ? 'clientes.erros.cpf' : 'clientes.erros.cnpj')
  if (soDigitos(form.postal_code).length !== 8) e.postal_code = t('clientes.erros.cep')
  if (!form.city.trim()) e.city = t('clientes.erros.obrigatorio')
  if (!form.state) e.state = t('clientes.erros.uf')
  return e
})
// Linha vazia não conta: só é ignorada no envio.
const errosTelefones = computed(() =>
  form.phones.map((v) => (v && !telefoneValido(v) ? t('clientes.erros.telefone') : undefined)),
)
const errosEmails = computed(() =>
  form.emails.map((v) =>
    v.trim() && !EMAIL.test(v.trim()) ? t('clientes.erros.email') : undefined,
  ),
)
const erroDe = (campo: keyof typeof vazio) => (tentou.value ? erros.value[campo] : undefined)
const rotuloDaLista = (rotulo: string, lista: string[], i: number) =>
  lista.length > 1 ? `${rotulo} ${i + 1}` : rotulo

const salvar = useAlteracao(
  (body: ClienteEntrada) =>
    props.id ? clientesApi.editar({ id: props.id, ...body }) : clientesApi.criar(body),
  // O nome do cliente aparece na lista e no detalhe dos chamados.
  ['clientes', 'cliente', 'chamados', 'chamado'],
)

async function enviar() {
  tentou.value = true
  erro.value = null
  if (
    Object.keys(erros.value).length ||
    errosTelefones.value.some(Boolean) ||
    errosEmails.value.some(Boolean)
  )
    return
  const opcional = (v: string) => v.trim() || null
  const preenchidos = (lista: string[]) => lista.map((v) => v.trim()).filter(Boolean)
  try {
    await salvar.mutateAsync({
      kind: form.kind,
      name: opcional(form.name),
      trade_name: pf.value ? null : opcional(form.trade_name),
      document: opcional(form.document),
      id_number: pf.value ? opcional(form.id_number) : null,
      birth_date: pf.value ? opcional(form.birth_date) : null,
      state_registration: pf.value ? null : opcional(form.state_registration),
      municipal_registration: pf.value ? null : opcional(form.municipal_registration),
      contact_name: pf.value ? null : opcional(form.contact_name),
      emails: preenchidos(form.emails),
      phones: preenchidos(form.phones),
      postal_code: form.postal_code,
      street: opcional(form.street),
      number: opcional(form.number),
      complement: opcional(form.complement),
      district: opcional(form.district),
      city: form.city.trim(),
      state: form.state,
      notes: opcional(form.notes),
      is_active: form.is_active,
    })
    toast.show({
      title: props.id ? t('comum.salvo') : t('clientes.cadastrado'),
      description: form.name || form.trade_name || `${form.city}/${form.state}`,
    })
    await router.push('/admin/clientes')
  } catch (e) {
    erro.value = (e as Error).message
  }
}
</script>

<template>
  <div class="mx-auto flex max-w-7xl flex-col gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="text-xl font-semibold">
        {{ id ? (cliente.data.value?.label ?? t('clientes.editar')) : t('clientes.novo') }}
      </h1>
      <div class="flex gap-2">
        <Button variant="secondary" @click="router.push('/admin/clientes')">
          {{ podeEditar ? t('comum.cancelar') : t('comum.fechar') }}
        </Button>
        <Button
          v-if="podeEditar"
          type="submit"
          form="form-cliente"
          :disabled="salvar.isPending.value || (!!id && !cliente.data.value)"
        >
          {{ t('comum.salvar') }}
        </Button>
      </div>
    </div>

    <p v-if="id && cliente.isError.value" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">
      {{ cliente.error.value?.message }}
    </p>
    <p v-else-if="id && cliente.isPending.value" class="text-muted">{{ t('comum.carregando') }}</p>

    <form v-else id="form-cliente" novalidate @submit.prevent="enviar">
      <p v-if="erro" class="mb-4 rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
      <fieldset :disabled="!podeEditar" class="grid items-start gap-4 lg:grid-cols-3">
        <section
          class="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4"
          aria-labelledby="dados-titulo"
        >
          <h2 id="dados-titulo" class="font-semibold">{{ t('clientes.dados') }}</h2>
          <RadioGroup v-model="form.kind" :legend="t('clientes.tipo')" :options="opcoesTipo" />
          <TextField
            v-model="form.name"
            :label="pf ? t('clientes.nomeCompleto') : t('clientes.razaoSocial')"
            :error="erroDe('name')"
            required
          />
          <TextField
            v-if="!pf"
            v-model="form.trade_name"
            :label="t('clientes.nomeFantasia')"
            :error="erroDe('trade_name')"
            required
          />
          <div class="grid gap-4 sm:grid-cols-2">
            <TextField
              v-model="form.document"
              :label="pf ? 'CPF' : 'CNPJ'"
              :error="erroDe('document')"
              required
            />
            <TextField v-if="pf" v-model="form.id_number" :label="t('clientes.rg')" />
            <TextField
              v-else
              v-model="form.state_registration"
              :label="t('clientes.inscricaoEstadual')"
              :hint="t('clientes.inscricaoEstadualDica')"
            />
          </div>
          <TextField
            v-if="pf"
            v-model="form.birth_date"
            type="date"
            :label="t('clientes.nascimento')"
          />
          <div v-else class="grid gap-4 sm:grid-cols-2">
            <TextField
              v-model="form.municipal_registration"
              :label="t('clientes.inscricaoMunicipal')"
            />
            <TextField v-model="form.contact_name" :label="t('clientes.pessoaDeContato')" />
          </div>
          <Checkbox v-if="id" v-model="form.is_active" :label="t('clientes.ativo')" />
        </section>

        <section
          class="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4"
          aria-labelledby="contato-titulo"
        >
          <h2 id="contato-titulo" class="font-semibold">{{ t('clientes.contato') }}</h2>
          <div v-for="(_, i) in form.phones" :key="`tel-${i}`" class="flex items-start gap-2">
            <div class="flex-1">
              <TextField
                :model-value="form.phones[i]"
                type="tel"
                :label="rotuloDaLista(t('clientes.telefone'), form.phones, i)"
                :error="tentou ? errosTelefones[i] : undefined"
                @update:model-value="form.phones[i] = formatarTelefone($event)"
              />
            </div>
            <Button
              v-if="podeEditar"
              variant="ghost"
              size="sm"
              class="mt-8"
              :aria-label="t('clientes.removerTelefone')"
              :title="t('clientes.removerTelefone')"
              @click="form.phones.splice(i, 1)"
            >
              <Trash2 class="size-4" aria-hidden="true" />
            </Button>
          </div>
          <Button
            v-if="podeEditar"
            variant="ghost"
            size="sm"
            class="self-start"
            @click="form.phones.push('')"
          >
            <Plus class="size-4" aria-hidden="true" /> {{ t('clientes.adicionarTelefone') }}
          </Button>
          <div v-for="(_, i) in form.emails" :key="`email-${i}`" class="flex items-start gap-2">
            <div class="flex-1">
              <TextField
                v-model="form.emails[i]"
                type="email"
                autocomplete="off"
                :label="rotuloDaLista(t('clientes.email'), form.emails, i)"
                :error="tentou ? errosEmails[i] : undefined"
              />
            </div>
            <Button
              v-if="podeEditar"
              variant="ghost"
              size="sm"
              class="mt-8"
              :aria-label="t('clientes.removerEmail')"
              :title="t('clientes.removerEmail')"
              @click="form.emails.splice(i, 1)"
            >
              <Trash2 class="size-4" aria-hidden="true" />
            </Button>
          </div>
          <Button
            v-if="podeEditar"
            variant="ghost"
            size="sm"
            class="self-start"
            @click="form.emails.push('')"
          >
            <Plus class="size-4" aria-hidden="true" /> {{ t('clientes.adicionarEmail') }}
          </Button>
          <TextAreaField v-model="form.notes" :label="t('clientes.observacoes')" :rows="5" />
        </section>

        <section
          class="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4"
          aria-labelledby="endereco-titulo"
        >
          <h2 id="endereco-titulo" class="font-semibold">{{ t('clientes.endereco') }}</h2>
          <div class="max-w-40">
            <TextField
              v-model="form.postal_code"
              :label="t('clientes.cep')"
              :error="erroDe('postal_code')"
              required
            />
          </div>
          <TextField v-model="form.street" :label="t('clientes.logradouro')" />
          <div class="grid grid-cols-[8rem_1fr] gap-4">
            <TextField v-model="form.number" :label="t('clientes.numero')" />
            <TextField v-model="form.complement" :label="t('clientes.complemento')" />
          </div>
          <TextField v-model="form.district" :label="t('clientes.bairro')" />
          <div class="grid grid-cols-[1fr_6rem] gap-4">
            <TextField
              v-model="form.city"
              :label="t('clientes.cidade')"
              :error="erroDe('city')"
              required
            />
            <SelectField
              v-model="form.state"
              :label="t('clientes.uf')"
              :options="opcoesUf"
              :error="erroDe('state')"
              required
            />
          </div>
        </section>
      </fieldset>
    </form>
  </div>
</template>
