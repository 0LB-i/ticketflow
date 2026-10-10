<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { SESSAO_EXPIRADA } from '@/api/client'
import AppLayout from '@/components/layout/AppLayout.vue'
import PublicLayout from '@/components/layout/PublicLayout.vue'
import ToastHost from '@/components/ui/ToastHost.vue'
import { definirIdioma } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useBrandingStore } from '@/stores/branding'
import { useThemeStore } from '@/stores/theme'

useThemeStore()
const auth = useAuthStore()
const branding = useBrandingStore()

// Idioma: o escolhido pela pessoa ou o padrão do sistema (configurações). Até a sessão ser
// consultada, vale o último idioma usado neste navegador (i18n/index.ts), para não piscar.
watchEffect(() => {
  if (auth.carregado) definirIdioma(auth.me?.locale ?? branding.idiomaPadrao)
})
const route = useRoute()
const router = useRouter()
const layout = computed(() => (route.meta.cartao ? PublicLayout : AppLayout))

// Sessão expirada no meio do uso: volta ao login e, depois, à página onde estava (docs/13 §13.3).
function sessaoExpirada() {
  if (route.meta.publica) return
  auth.esquecer()
  router.push({ name: 'login', query: { volta: route.fullPath, expirou: '1' } })
}
onMounted(() => window.addEventListener(SESSAO_EXPIRADA, sessaoExpirada))
onBeforeUnmount(() => window.removeEventListener(SESSAO_EXPIRADA, sessaoExpirada))
</script>

<template>
  <component :is="layout">
    <RouterView />
  </component>
  <ToastHost />
</template>
