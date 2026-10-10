import { createI18n } from 'vue-i18n'

import ptBR from './pt-BR.json'

export type Mensagens = typeof ptBR

export const i18n = createI18n<[Mensagens], 'pt-BR', false>({
  legacy: false,
  locale: 'pt-BR',
  fallbackLocale: 'pt-BR',
  messages: { 'pt-BR': ptBR },
})
