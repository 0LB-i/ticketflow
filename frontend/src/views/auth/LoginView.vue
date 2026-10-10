<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import TextField from '@/components/ui/TextField.vue'
import { useHead } from '@/composables/useHead'
import { useAuthStore } from '@/stores/auth'

useHead('login.titulo')
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const login = ref('')
const senha = ref('')
const erro = ref<string | null>(null)
const enviando = ref(false)

async function entrar() {
  enviando.value = true
  erro.value = await auth.entrar(login.value, senha.value)
  enviando.value = false
  if (erro.value) return
  const volta = typeof route.query.volta === 'string' && route.query.volta.startsWith('/')
  await router.replace(volta ? (route.query.volta as string) : { name: 'chamados' })
}
</script>

<template>
  <form class="flex flex-col gap-4" novalidate @submit.prevent="entrar">
    <h1 class="text-lg font-semibold">{{ $t('login.titulo') }}</h1>
    <p
      v-if="route.query.expirou && !erro"
      class="rounded-md bg-primary-subtle p-3 text-fg"
      role="status"
    >
      {{ $t('login.expirou') }}
    </p>
    <p v-if="erro" class="rounded-md bg-red-bg p-3 text-red-fg" role="alert">{{ erro }}</p>
    <TextField v-model="login" :label="$t('login.usuario')" autocomplete="username" required />
    <TextField
      v-model="senha"
      :label="$t('login.senha')"
      type="password"
      autocomplete="current-password"
      required
    />
    <Button type="submit" :disabled="enviando || !login || !senha">
      {{ enviando ? $t('login.entrando') : $t('login.entrar') }}
    </Button>
    <RouterLink to="/esqueci-senha" class="text-center text-primary underline">
      {{ $t('login.esqueci') }}
    </RouterLink>
  </form>
</template>
