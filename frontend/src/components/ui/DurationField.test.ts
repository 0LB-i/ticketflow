import { afterEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import { montar } from '@/test/setup'

import DurationField from './DurationField.vue'

const montados: { unmount: () => void }[] = []
afterEach(() => {
  montados.splice(0).forEach((w) => w.unmount())
  document.body.innerHTML = ''
})

function montarCampo(inicial = '') {
  const valor = ref(inicial)
  const w = montar(DurationField, {
    props: {
      label: 'Tempo gasto',
      modelValue: valor.value,
      'onUpdate:modelValue': (v: string) => {
        valor.value = v
        w.setProps({ modelValue: v })
      },
    },
    attachTo: document.body,
  })
  montados.push(w)
  return { w, valor }
}

describe('DurationField', () => {
  it('digitado, preenche hh:mm pela direita e recusa letras', async () => {
    const { w, valor } = montarCampo()
    const input = w.get('input')
    await input.setValue('130')
    expect(valor.value).toBe('01:30')
    expect((input.element as HTMLInputElement).value).toBe('01:30')
    await input.setValue('01:30a')
    expect((input.element as HTMLInputElement).value).toBe('01:30')
  })

  it('lista os horários sugeridos e escolhe um deles', async () => {
    const { w, valor } = montarCampo('00:45')
    await w.get('button[aria-label="Tempo gasto"]').trigger('click')
    const opcoes = await vi.waitFor(() => {
      const lista = [...document.querySelectorAll('[role=option]')]
      expect(lista.length).toBeGreaterThan(0)
      return lista as HTMLElement[]
    })
    expect(opcoes.map((o) => o.textContent?.trim()).slice(0, 4)).toEqual([
      '00:20',
      '00:30',
      '00:45',
      '01:00',
    ])
    opcoes.find((o) => o.textContent?.trim() === '02:15')!.click()
    expect(valor.value).toBe('02:15')
    await w.vm.$nextTick()
    expect((w.get('input').element as HTMLInputElement).value).toBe('02:15')
  })
})
