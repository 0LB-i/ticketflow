<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { api, mensagemDeErro } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import TextField from '@/components/ui/TextField.vue'
import { useHead } from '@/composables/useHead'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

/** Troca obrigatória da senha provisória, logo depois do primeiro acesso (docs/09 §9.2). */
useHead('trocarSenha.titulo')
const { t } = useI18n()
const router = useRouter()
const toast = useToast()
const auth = useAuthStore()

const senha = ref('')
const confirmar = ref('')
const erro = ref<string | null>(null)
const enviando = ref(false)
const naoConfere = computed(() => confirmar.value !== '' && confirmar.value !== senha.value)

async function salvar() {
  if (senha.value !== confirmar.value) return
  enviando.value = true
  const { error } = await api.POST('/api/v1/me/password', {
    body: { new_password: senha.value },
  })
  enviando.value = false
  if (error !== undefined) {
    erro.value = mensagemDeErro(error, t('comum.erroInesperado'))
    return
  }
  await auth.carregar()
  toast.show({ title: t('trocarSenha.pronto') })
  await router.replace({ name: 'chamados' })
}

async function sair() {
  await auth.sair()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <form class="flex flex-col gap-4" novalidate @submit.prevent="salvar">
    <h1 class="text-lg font-semibold">{{ $t('trocarSenha.titulo') }}</h1>
    <p class="text-muted">{{ $t('trocarSenha.texto') }}</p>
    <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
    <TextField
      v-model="senha"
      :label="$t('definirSenha.senha')"
      :hint="$t('definirSenha.dica')"
      type="password"
      autocomplete="new-password"
      required
    />
    <TextField
      v-model="confirmar"
      :label="$t('definirSenha.confirmar')"
      :error="naoConfere ? $t('definirSenha.naoConfere') : undefined"
      type="password"
      autocomplete="new-password"
      required
    />
    <Button type="submit" :disabled="enviando || senha.length < 8 || senha !== confirmar">
      {{ $t('trocarSenha.salvar') }}
    </Button>
    <Button variant="ghost" @click="sair">{{ $t('trocarSenha.sair') }}</Button>
  </form>
</template>
