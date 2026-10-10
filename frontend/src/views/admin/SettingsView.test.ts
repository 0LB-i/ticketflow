import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import { useBrandingStore } from '@/stores/branding'
import { montar, simularApi } from '@/test/setup'

import SettingsView from './SettingsView.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
  document.getElementById('tf-cores')?.remove()
  localStorage.clear()
})

const PADRAO = { default_locale: 'pt-BR', colors: null, logo_url: null }

async function preencher(input: HTMLInputElement, valor: string) {
  input.value = valor
  input.dispatchEvent(new Event('input'))
  await nextTick()
}

describe('SettingsView', () => {
  it('troca a cor da marca, mostra a prévia ajustada e aplica ao salvar', async () => {
    const amarelo = { brand: '#FDE047', neutral: '#737373', background: '#FFFFFF' }
    const feitas = simularApi({
      'PATCH /api/v1/admin/settings': [200, { ...PADRAO, default_locale: 'en', colors: amarelo }],
    })
    const w = montar(SettingsView)
    useBrandingStore().aplicar(PADRAO as never)

    await preencher(w.get('#cor-brand').element as HTMLInputElement, '#FDE047')
    // Amarelo claro não dá para ler sobre branco: o tom dos botões e links é escurecido.
    expect(w.text()).toContain('Tom ajustado para leitura')
    const previa = w.findAll('[style*="--tf-primary"]')[0]!.attributes('style')!
    expect(previa).toContain('--tf-brand: #FDE047')
    expect(previa).not.toContain('--tf-primary: #FDE047')

    await w.get('form').trigger('submit')
    await vi.waitFor(() => expect(document.getElementById('tf-cores')).not.toBeNull())
    expect(feitas[0]!.corpo).toEqual({ default_locale: 'pt-BR', colors: amarelo })
    expect(document.getElementById('tf-cores')!.textContent).toContain(
      'html:root{--tf-brand:#FDE047',
    )
    expect(localStorage.getItem('tf-cores')).toContain('html.dark{')
  })

  it('cores iguais às do padrão voltam ao padrão (null)', async () => {
    const feitas = simularApi({ 'PATCH /api/v1/admin/settings': [200, PADRAO] })
    const w = montar(SettingsView)
    await w.get('form').trigger('submit')
    await vi.waitFor(() => expect(feitas).toHaveLength(1))
    expect(feitas[0]!.corpo).toEqual({ default_locale: 'pt-BR', colors: null })
  })

  it('não salva cor malformada', async () => {
    const w = montar(SettingsView)
    await preencher(w.get('#cor-neutral').element as HTMLInputElement, '#12')
    expect(w.text()).toContain('Use o formato #RRGGBB.')
    expect(w.get('button[type=submit]').attributes('disabled')).toBeDefined()
  })

  it('recusa logotipo que não é imagem aceita, sem enviar', async () => {
    const feitas = simularApi({})
    const w = montar(SettingsView)
    const input = w.get('input[type=file]').element as HTMLInputElement
    const svg = new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' })
    Object.defineProperty(input, 'files', { value: [svg] })
    input.dispatchEvent(new Event('change'))
    await nextTick()
    expect(w.get('[role=alert]').text()).toBe('Envie uma imagem PNG, JPEG ou WebP.')
    expect(feitas).toHaveLength(0)
  })
})
