import { afterEach, describe, expect, it, vi } from 'vitest'

import { criarRouter } from '@/router'
import { escolher, ME_AGENTE, montar, simularApi } from '@/test/setup'

import ClientFormView from './ClientFormView.vue'
import ClientsView from './ClientsView.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const ME = { ...ME_AGENTE, permissions: ['client.view', 'client.manage'] }
const ID = '00000000-0000-0000-0000-0000000000e1'

/** Preenche o TextField pelo rótulo. */
async function digitar(w: ReturnType<typeof montar>, rotulo: string, valor: string) {
  const label = w.findAll('label').find((l) => l.text().replace(' *', '') === rotulo)!
  await w.get(`#${label.attributes('for')}`).setValue(valor)
}

describe('ClientFormView', () => {
  it('cadastra pessoa jurídica com as máscaras e só os campos de PJ', async () => {
    const feitas = simularApi({
      'GET /api/v1/me': [200, ME],
      'POST /api/v1/clients': [201, { id: ID, name: 'Padaria Pão Quente Ltda' }],
      'GET /api/v1/clients': [200, { items: [], total: 0 }],
    })
    const router = criarRouter()
    const w = montar(ClientFormView, { global: { plugins: [router] }, attachTo: document.body })
    await router.push('/clientes/novo')
    await vi.waitFor(() => expect(w.text()).toContain('Pessoa jurídica (CNPJ)'))

    await w
      .findAll('label')
      .find((l) => l.text().includes('Pessoa jurídica'))!
      .get('input')
      .setValue()
    await digitar(w, 'Razão social', 'Padaria Pão Quente Ltda')
    await digitar(w, 'Nome fantasia', 'Pão Quente')
    await digitar(w, 'CNPJ', '12abc34501de35')
    await digitar(w, 'E-mail', 'contato@paoquente.com.br')
    await digitar(w, 'Telefone', '1133334444')
    await digitar(w, 'CEP', '01310100')
    await digitar(w, 'Logradouro', 'Avenida Paulista')
    await digitar(w, 'Número', '1000')
    await digitar(w, 'Bairro', 'Bela Vista')
    await digitar(w, 'Cidade', 'São Paulo')
    await escolher('UF', 'SP')
    expect(w.text()).not.toContain('Data de nascimento')

    await w.get('form').trigger('submit')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/clientes'))
    expect(feitas.find((r) => r.metodo === 'POST')!.corpo).toMatchObject({
      kind: 'company',
      name: 'Padaria Pão Quente Ltda',
      trade_name: 'Pão Quente',
      document: '12.ABC.345/01DE-35',
      id_number: null,
      birth_date: null,
      phone: '(11) 3333-4444',
      postal_code: '01310-100',
      state: 'SP',
    })
  })

  it('não envia com CPF inválido e campos obrigatórios vazios', async () => {
    const feitas = simularApi({ 'GET /api/v1/me': [200, ME] })
    const w = montar(ClientFormView, { global: { plugins: [criarRouter()] } })
    await vi.waitFor(() => expect(w.find('form').exists()).toBe(true))
    await digitar(w, 'CPF', '52998224724')
    await w.get('form').trigger('submit')
    expect(w.text()).toContain('CPF inválido.')
    expect(w.text()).toContain('Informe um e-mail válido.')
    expect(w.text()).toContain('O CEP tem 8 números.')
    expect(feitas.some((r) => r.metodo === 'POST')).toBe(false)
  })
})

describe('ClientsView', () => {
  it('lista com o documento e o telefone formatados', async () => {
    simularApi({
      'GET /api/v1/me': [200, ME],
      'GET /api/v1/clients': [
        200,
        {
          items: [
            {
              id: ID,
              kind: 'person',
              name: 'João da Silva',
              trade_name: null,
              document: '52998224725',
              email: 'joao@exemplo.com',
              phone: '11987654321',
              city: 'São Paulo',
              state: 'SP',
              is_active: true,
            },
          ],
          total: 1,
        },
      ],
    })
    const w = montar(ClientsView, { global: { plugins: [criarRouter()] } })
    await vi.waitFor(() => expect(w.text()).toContain('João da Silva'))
    expect(w.text()).toContain('529.982.247-25')
    expect(w.text()).toContain('(11) 98765-4321')
    expect(w.text()).toContain('Novo cliente')
  })
})
