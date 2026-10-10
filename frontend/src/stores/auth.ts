import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, mensagemDeErro, type Schemas } from '@/api/client'

/** Usuário logado (docs/09). As permissões vêm do backend e só decidem o que mostrar. */
export const useAuthStore = defineStore('auth', () => {
  const me = ref<Schemas['Me'] | null>(null)
  const carregado = ref(false)

  const logado = computed(() => me.value !== null)

  async function carregar(): Promise<void> {
    const { data } = await api.GET('/api/v1/me')
    me.value = data ?? null
    carregado.value = true
  }

  async function entrar(email: string, password: string): Promise<string | null> {
    const { error, response } = await api.POST('/api/v1/auth/login', {
      body: { email, password },
    })
    if (error !== undefined) {
      return response.status === 429
        ? mensagemDeErro(error, 'Muitas tentativas. Tente de novo mais tarde.')
        : mensagemDeErro(error, 'Não foi possível entrar.')
    }
    await carregar()
    return null
  }

  async function sair(): Promise<void> {
    await api.POST('/api/v1/auth/logout')
    me.value = null
  }

  function esquecer(): void {
    me.value = null
  }

  function pode(permissao: string): boolean {
    return me.value?.permissions.includes(permissao) ?? false
  }

  return { me, carregado, logado, carregar, entrar, sair, esquecer, pode }
})
