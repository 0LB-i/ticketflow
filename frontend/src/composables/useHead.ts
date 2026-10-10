import { watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'

/** Título da aba: "<página> · TicketFlow" (docs/17 §17.1). */
export function useHead(chaveTitulo: string) {
  const { t } = useI18n()
  watchEffect(() => {
    document.title = `${t(chaveTitulo)} · ${t('app.nome')}`
  })
}
