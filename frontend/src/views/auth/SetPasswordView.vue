<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { api, mensagemDeErro } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import TextField from '@/components/ui/TextField.vue'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'

/** Convite (primeiro acesso) e redefinição de senha: mesma tela, rotas diferentes. */
const props = defineProps<{ token: string; tipo: 'convite' | 'redefinir' }>()

const { t } = useI18n()
const router = useRouter()
const toast = useToast()
useHead(props.tipo === 'convite' ? 'definirSenha.tituloConvite' : 'definirSenha.tituloRedefinir')

const info = useQuery({
  queryKey: ['token', props.token],
  queryFn: async () => {
    const { data } = await api.GET('/api/v1/auth/tokens/{token}', {
      params: { path: { token: props.token } },
    })
    return data ?? null
  },
  retry: false,
})

const senha = ref('')
const confirmar = ref('')
const erro = ref<string | null>(null)
const enviando = ref(false)
const naoConfere = computed(() => confirmar.value !== '' && confirmar.value !== senha.value)

async function salvar() {
  if (senha.value !== confirmar.value) return
  enviando.value = true
  const rota =
    props.tipo === 'convite' ? '/api/v1/auth/invite/accept' : '/api/v1/auth/password/reset'
  const { error } = await api.POST(rota, { body: { token: props.token, password: senha.value } })
  enviando.value = false
  if (error !== undefined) {
    erro.value = mensagemDeErro(error, t('comum.erroInesperado'))
    return
  }
  toast.show({ title: t('definirSenha.pronto') })
  await router.replace({ name: 'login' })
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <h1 class="text-lg font-semibold">
      {{
        tipo === 'convite' ? $t('definirSenha.tituloConvite') : $t('definirSenha.tituloRedefinir')
      }}
    </h1>
    <p v-if="info.isPending.value" class="text-muted">{{ $t('comum.carregando') }}</p>
    <template v-else-if="!info.data.value">
      <p class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">
        {{ $t('definirSenha.invalido') }}
      </p>
      <RouterLink to="/esqueci-senha" class="text-center text-primary underline">
        {{ $t('definirSenha.pedirOutro') }}
      </RouterLink>
    </template>
    <form v-else class="flex flex-col gap-4" novalidate @submit.prevent="salvar">
      <p class="text-muted">
        {{
          $t('definirSenha.para', { nome: info.data.value.full_name, email: info.data.value.email })
        }}
      </p>
      <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
      <TextField
        v-model="senha"
        :label="$t('definirSenha.senha')"
        :hint="$t('definirSenha.dica')"
        type="password"
        required
      />
      <TextField
        v-model="confirmar"
        :label="$t('definirSenha.confirmar')"
        :error="naoConfere ? $t('definirSenha.naoConfere') : undefined"
        type="password"
        required
      />
      <Button type="submit" :disabled="enviando || senha.length < 8 || senha !== confirmar">
        {{ $t('definirSenha.salvar') }}
      </Button>
    </form>
  </div>
</template>
