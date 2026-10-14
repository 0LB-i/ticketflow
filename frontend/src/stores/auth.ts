import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, mensagemDeErro, ou, type Schemas } from '@/api/client'
import { i18n, type Idioma } from '@/i18n'

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

  /** `login`: e-mail ou nome de usuário (o administrador padrão entra com "admin"). */
  async function entrar(login: string, password: string): Promise<string | null> {
    const { error, response } = await api.POST('/api/v1/auth/login', {
      body: { login, password },
    })
    if (error !== undefined) {
      return response.status === 429
        ? mensagemDeErro(error, i18n.global.t('login.muitasTentativas'))
        : mensagemDeErro(error, i18n.global.t('login.falhou'))
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
    entrar,
    sair,
    esquecer,
    mudarIdioma,
    pode,
  }
})
