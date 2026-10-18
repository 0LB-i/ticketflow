// Configurações (templates/admin/settings.html): combinações prontas e seletor de cor, a
// explicação do comportamento de status e a lista de feriados. JavaScript puro (ADR 0011).

const CAMPOS_DE_COR = ['brand', 'neutral', 'background']

/** Marca a combinação pronta igual às três cores digitadas. */
function marcarPredefinida() {
  const atual = Object.fromEntries(
    CAMPOS_DE_COR.map((c) => [c, document.getElementById(`cor-${c}`).value.toUpperCase()]),
  )
  for (const botao of document.querySelectorAll('[data-predefinida]')) {
    const cores = JSON.parse(botao.dataset.predefinida)
    botao.setAttribute('aria-pressed', String(CAMPOS_DE_COR.every((c) => cores[c] === atual[c])))
  }
}

/** Muda o valor e avisa o formulário (o HTMX pede a prévia nova). */
function definirCor(campo, valor) {
  campo.value = valor.toUpperCase()
  const seletor = document.querySelector(`[data-seletor-de="${campo.id}"]`)
  if (seletor && /^#[0-9a-f]{6}$/i.test(valor)) seletor.value = valor.toLowerCase()
  campo.dispatchEvent(new Event('input', { bubbles: true }))
}

document.addEventListener('click', (e) => {
  const botao = e.target.closest('[data-predefinida]')
  if (!botao) return
  const cores = JSON.parse(botao.dataset.predefinida)
  for (const c of CAMPOS_DE_COR) definirCor(document.getElementById(`cor-${c}`), cores[c])
})

document.addEventListener('input', (e) => {
  const seletor = e.target.closest('[data-seletor-de]')
  if (seletor) definirCor(document.getElementById(seletor.dataset.seletorDe), seletor.value)
  if (e.target.id?.startsWith('cor-')) {
    const outro = document.querySelector(`[data-seletor-de="${e.target.id}"]`)
    if (outro && /^#[0-9a-f]{6}$/i.test(e.target.value)) outro.value = e.target.value.toLowerCase()
    marcarPredefinida()
  }
})

// A explicação do comportamento escolhido para o status novo.
document.addEventListener('change', (e) => {
  if (e.target.name !== 'kind') return
  for (const p of document.querySelectorAll('[data-explica]')) p.hidden = p.dataset.explica !== e.target.value
})

// Feriados: acrescentar (em ordem, sem repetir) e tirar. Só vão para o servidor ao salvar.
const formatoData = new Intl.DateTimeFormat(document.documentElement.lang || 'pt-BR', {
  timeZone: 'UTC',
})
const dataLegivel = (iso) => formatoData.format(new Date(`${iso}T00:00:00Z`))

document.addEventListener('click', (e) => {
  const adicionar = e.target.closest('[data-adiciona-feriado]')
  if (adicionar) {
    const caixa = adicionar.closest('[data-feriados]')
    const campo = caixa.querySelector('[data-novo-feriado]')
    const iso = campo.value
    campo.value = ''
    const lista = caixa.querySelector('[data-lista]')
    if (!iso || lista.querySelector(`[data-data="${iso}"]`)) return
    const item = caixa.querySelector('template').content.firstElementChild.cloneNode(true)
    item.dataset.data = iso
    item.querySelector('span').textContent = dataLegivel(iso)
    item.querySelector('input').value = iso
    item.querySelector('button').setAttribute('aria-label', caixa.dataset.remover.replace('{data}', dataLegivel(iso)))
    const depois = [...lista.children].find((li) => li.dataset.data > iso)
    lista.insertBefore(item, depois ?? null)
  }
  e.target.closest('[data-remove-feriado]')?.closest('[data-data]').remove()
})
