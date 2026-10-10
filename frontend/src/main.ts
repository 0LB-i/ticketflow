import './assets/main.css'

import { VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { i18n } from './i18n'
import { router } from './router'
import { useBrandingStore } from './stores/branding'

const pinia = createPinia()
const app = createApp(App).use(pinia).use(router).use(i18n).use(VueQueryPlugin)

// Cores, logotipo e idioma padrão antes da primeira tela (inclusive a de login).
useBrandingStore(pinia)
  .carregar()
  .catch(() => {
    // sem a API, a interface abre com o padrão
  })
  .finally(() => app.mount('#app'))
