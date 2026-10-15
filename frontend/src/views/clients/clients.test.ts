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
    await router.push('/admin/clientes/novo')
    await vi.waitFor(() => expect(w.text()).toContain('Pessoa jurídica (CNPJ)'))

    await w
      .findAll('label')
      .find((l) => l.text().includes('Pessoa jurídica'))!
      .get('input')
      .setValue()
    await digitar(w, 'Razão social', 'Padaria Pão Quente Ltda')
    await digitar(w, 'Nome fantasia', 'Pão Quente')
    await digitar(w, 'CNPJ', '12abc34501de35')
    await digitar(w, 'Telefone', '1133334444')
    await w
      .findAll('button')
      .find((b) => b.text() === 'Adicionar telefone')!
      .trigger('click')
    await digitar(w, 'Telefone 2', '11987654321')
    await digitar(w, 'E-mail', 'contato@paoquente.com.br')
    await w
      .findAll('button')
      .find((b) => b.text() === 'Adicionar e-mail')!
      .trigger('click')
    await w
      .findAll('button')
      .find((b) => b.text() === 'Adicionar e-mail')!
      .trigger('click')
    await digitar(w, 'E-mail 3', 'nao-envia@x.com')
    // Remove o terceiro; o segundo, vazio, fica de fora do envio
    await w.findAll('button[aria-label="Remover e-mail"]')[2]!.trigger('click')
    await digitar(w, 'CEP', '01310100')
    await digitar(w, 'Logradouro', 'Avenida Paulista')
    await digitar(w, 'Número', '1000')
    await digitar(w, 'Bairro', 'Bela Vista')
    await digitar(w, 'Cidade', 'São Paulo')
    await escolher('UF', 'SP')
    expect(w.text()).not.toContain('Data de nascimento')

    await w.get('form').trigger('submit')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/admin/clientes'))
    expect(feitas.find((r) => r.metodo === 'POST')!.corpo).toMatchObject({
      kind: 'company',
      name: 'Padaria Pão Quente Ltda',
      trade_name: 'Pão Quente',
      document: '12.ABC.345/01DE-35',
      id_number: null,
      birth_date: null,
      phones: ['(11) 3333-4444', '(11) 98765-4321'],
      emails: ['contato@paoquente.com.br'],
      postal_code: '01310-100',
      state: 'SP',
    })
  })

  it('CPF e RG só aceitam números: o CPF no máximo 11, o RG no máximo 14', async () => {
    simularApi({ 'GET /api/v1/me': [200, ME] })
    const w = montar(ClientFormView, { global: { plugins: [criarRouter()] } })
    await vi.waitFor(() => expect(w.find('form').exists()).toBe(true))
    const campo = (rotulo: string) => {
      const label = w.findAll('label').find((l) => l.text().replace(' *', '') === rotulo)!
      return w.get<HTMLInputElement>(`#${label.attributes('for')}`).element
    }
    await digitar(w, 'CPF', '529.982.247-25')
    await digitar(w, 'CPF', '529.982.247-251')
    await vi.waitFor(() => expect(campo('CPF').value).toBe('529.982.247-25'))
    await digitar(w, 'CPF', '529.982.247-25a')
    await vi.waitFor(() => expect(campo('CPF').value).toBe('529.982.247-25'))
    await digitar(w, 'RG', '12.345.678-x9')
    await vi.waitFor(() => expect(campo('RG').value).toBe('123456789'))
    await digitar(w, 'RG', '123456789012345')
    await vi.waitFor(() => expect(campo('RG').value).toBe('12345678901234'))
  })

  it('não envia com CPF ou e-mail inválido e sem CEP, cidade e UF', async () => {
    const feitas = simularApi({ 'GET /api/v1/me': [200, ME] })
    const w = montar(ClientFormView, { global: { plugins: [criarRouter()] } })
    await vi.waitFor(() => expect(w.find('form').exists()).toBe(true))
    await digitar(w, 'CPF', '52998224724')
    await digitar(w, 'E-mail', 'joao')
    await w.get('form').trigger('submit')
    expect(w.text()).toContain('CPF inválido.')
    expect(w.text()).toContain('Informe um e-mail válido.')
    expect(w.text()).toContain('O CEP tem 8 números.')
    expect(w.text()).toContain('Campo obrigatório.')
    expect(w.text()).toContain('Escolha a UF.')
    expect(w.text()).not.toContain('Informe o nome.')
    expect(feitas.some((r) => r.metodo === 'POST')).toBe(false)
  })

  it('PJ não envia sem razão social, nome fantasia e CNPJ', async () => {
    const feitas = simularApi({ 'GET /api/v1/me': [200, ME] })
    const w = montar(ClientFormView, { global: { plugins: [criarRouter()] } })
    await vi.waitFor(() => expect(w.find('form').exists()).toBe(true))
    await w
      .findAll('input[type=radio]')
      .find((r) => r.attributes('value') === 'company')!
      .setValue()
    await digitar(w, 'CEP', '01310100')
    await digitar(w, 'Cidade', 'São Paulo')
    await escolher('UF', 'SP')
    await w.get('form').trigger('submit')
    for (const rotulo of ['Razão social', 'Nome fantasia', 'CNPJ']) {
      const label = w.findAll('label').find((l) => l.text().replace(' *', '') === rotulo)!
      expect(label.text()).toContain('*')
      const dica = w.get(`#${label.attributes('for')}`).attributes('aria-describedby')!
      expect(w.get(`#${dica}`).text()).toBe('Campo obrigatório.')
    }
    expect(feitas.some((r) => r.metodo === 'POST')).toBe(false)
  })

  it('cadastra pessoa física só com nome, CPF, CEP, cidade e UF', async () => {
    const feitas = simularApi({
      'GET /api/v1/me': [200, ME],
      'POST /api/v1/clients': [201, { id: ID }],
      'GET /api/v1/clients': [200, { items: [], total: 0 }],
    })
    const router = criarRouter()
    const w = montar(ClientFormView, { global: { plugins: [router] }, attachTo: document.body })
    await router.push('/admin/clientes/novo')
    await vi.waitFor(() => expect(w.find('form').exists()).toBe(true))
    await digitar(w, 'Nome completo', 'João da Silva')
    await digitar(w, 'CPF', '52998224725')
    await digitar(w, 'CEP', '01310100')
    await digitar(w, 'Cidade', 'São Paulo')
    await escolher('UF', 'SP')
    await w.get('form').trigger('submit')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/admin/clientes'))
    expect(feitas.find((r) => r.metodo === 'POST')!.corpo).toMatchObject({
      name: 'João da Silva',
      document: '529.982.247-25',
      trade_name: null,
      street: null,
      phones: [],
      emails: [],
      city: 'São Paulo',
    })
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
              label: 'João da Silva',
              name: 'João da Silva',
              trade_name: null,
              document: '529.982.247-25',
              emails: ['joao@exemplo.com'],
              phones: ['11987654321', '1133334444'],
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
