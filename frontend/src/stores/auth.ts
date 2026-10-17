import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, ou, type Schemas } from '@/api/client'
import type { Idioma } from '@/i18n'

/** Usuário logado (docs/09). As permissões vêm do backend e só decidem o que mostrar. */
export const useAuthStore = defineStore('auth', () => {
  const me = ref<Schemas['Me'] | null>(null)
  const carregado = ref(false)

  const logado = computed(() => me.value !== null)
  const precisaTrocarSenha = computed(() => me.value?.must_change_password ?? false)

  async function carregar(): Promise<void> {
    const { data } = await api.GET('/api/v1/me')
    me.value = data ?? null
    carregado.value = true
  }

  async function sair(): Promise<void> {
    await api.POST('/api/v1/auth/logout')
    me.value = null
  }

  function esquecer(): void {
    me.value = null
  }

  /** Idioma da pessoa; nulo volta ao padrão do sistema. */
  async function mudarIdioma(locale: Idioma | null): Promise<void> {
    me.value = ou(await api.PATCH('/api/v1/me', { body: { locale } }))
  }

  function pode(permissao: string): boolean {
    return me.value?.permissions.includes(permissao) ?? false
  }

  return {
    me,
    carregado,
    logado,
    precisaTrocarSenha,
    carregar,
    sair,
    esquecer,
    mudarIdioma,
    pode,
  }
})
