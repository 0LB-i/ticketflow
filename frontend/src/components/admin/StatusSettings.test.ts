import { afterEach, describe, expect, it, vi } from 'vitest'

import { escolher, montar, simularApi } from '@/test/setup'

import StatusSettings from './StatusSettings.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const s = (id: number, name: string, kind: string, is_default: boolean, ticket_count = 0) => ({
  id,
  name,
  kind,
  is_default,
  ticket_count,
})
const LISTA = {
  items: [
    s(1, 'Pendente', 'open', true, 4),
    s(2, 'Aguardando cliente', 'waiting', true),
    s(5, 'Entregue', 'closed', false, 2),
    s(3, 'Concluído', 'closed', true),
    s(4, 'Cancelado', 'canceled', true),
  ],
}

describe('StatusSettings', () => {
  it('cria um status com o comportamento escolhido', async () => {
    const feitas = simularApi({
      'GET /api/v1/statuses': [200, LISTA],
      'POST /api/v1/statuses': [201, LISTA],
    })
    const w = montar(StatusSettings, { attachTo: document.body })
    await vi.waitFor(() => expect(w.text()).toContain('Aguardando cliente'))
    expect(w.text()).toContain('4 chamados')

    await w.findAll('input[type=text]').at(-1)!.setValue('Aguardando fornecedor')
    await escolher('Comportamento', 'Em espera')
    await w.findAll('form').at(-1)!.trigger('submit')
    await vi.waitFor(() =>
      expect(feitas.find((r) => r.metodo === 'POST')?.corpo).toEqual({
        name: 'Aguardando fornecedor',
        kind: 'waiting',
      }),
    )
  })

  it('remover avisa para onde vão os chamados; o único do comportamento não sai', async () => {
    const feitas = simularApi({
      'GET /api/v1/statuses': [200, LISTA],
      'DELETE /api/v1/statuses/5': [200, LISTA],
    })
    const w = montar(StatusSettings, { attachTo: document.body })
    await vi.waitFor(() => expect(w.text()).toContain('Entregue'))

    const botao = (rotulo: string) => w.find(`button[aria-label="${rotulo}"]`)
    expect(botao('Remover Cancelado').attributes('disabled')).toBeDefined()

    await botao('Remover Entregue').trigger('click')
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(
        'Os 2 chamados com este status passam para Concluído.',
      ),
    )
    const confirmar = [...document.querySelectorAll('[role=dialog] button')].find(
      (b) => b.textContent?.trim() === 'Remover',
    ) as HTMLButtonElement
    confirmar.click()
    await vi.waitFor(() => expect(feitas.some((r) => r.metodo === 'DELETE')).toBe(true))
  })
})
