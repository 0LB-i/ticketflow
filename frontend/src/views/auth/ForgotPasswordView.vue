<script setup lang="ts">
import { ref } from 'vue'

import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import TextField from '@/components/ui/TextField.vue'
import { useHead } from '@/composables/useHead'

useHead('esqueci.titulo')
const email = ref('')
const enviado = ref(false)
const enviando = ref(false)

async function enviar() {
  enviando.value = true
  // A resposta é sempre a mesma, exista o e-mail ou não (docs/09 §9.4).
  await api.POST('/api/v1/auth/password/forgot', { body: { email: email.value } })
  enviando.value = false
  enviado.value = true
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <h1 class="text-lg font-semibold">{{ $t('esqueci.titulo') }}</h1>
    <p v-if="enviado" class="rounded-md bg-green-bg p-3 text-green-fg" role="status">
      {{ $t('esqueci.enviado') }}
    </p>
    <form v-else class="flex flex-col gap-4" novalidate @submit.prevent="enviar">
      <p class="text-muted">{{ $t('esqueci.texto') }}</p>
      <TextField v-model="email" :label="$t('login.email')" type="email" required />
      <Button type="submit" :disabled="enviando || !email.includes('@')">
        {{ $t('esqueci.enviar') }}
      </Button>
    </form>
    <RouterLink to="/login" class="text-center text-primary underline">
      {{ $t('esqueci.voltar') }}
    </RouterLink>
  </div>
</template>
