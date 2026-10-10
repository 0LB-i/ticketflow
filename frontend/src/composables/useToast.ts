import { ref } from 'vue'

export interface Aviso {
  id: number
  title: string
  description?: string
  variant: 'success' | 'error'
}

const avisos = ref<Aviso[]>([])
let proximo = 0

/** Avisos temporários no canto da tela (docs/13 §13.6). Exibidos pelo ToastHost. */
export function useToast() {
  function show(aviso: Omit<Aviso, 'id' | 'variant'> & { variant?: Aviso['variant'] }) {
    avisos.value.push({ variant: 'success', ...aviso, id: ++proximo })
  }
  function remove(id: number) {
    avisos.value = avisos.value.filter((a) => a.id !== id)
  }
  return { avisos, show, remove }
}
