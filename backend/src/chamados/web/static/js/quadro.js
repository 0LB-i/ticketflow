// Quadro (kanban): arrastar um cartão para outra coluna muda o status do chamado. O cartão leva
// o formulário de status do detalhe, com os status para onde pode ir em data-destinos; soltar
// preenche o status da coluna e envia, e a página volta com o quadro atualizado. No mês passado,
// as colunas de concluídos e cancelados (data-data-de) levam a data escolhida no topo.
let arrastado = null

// O formulário do cartão, se o chamado pode ir para a coluna.
function formPara(cartao, coluna) {
  const form = cartao.querySelector('form[data-destinos]')
  return form?.dataset.destinos.split(' ').includes(coluna.dataset.coluna) ? form : null
}

function destacar(coluna) {
  for (const c of document.querySelectorAll('[data-coluna][data-alvo]')) {
    if (c !== coluna) c.removeAttribute('data-alvo')
  }
  coluna?.setAttribute('data-alvo', '')
}

function enviar(cartao, coluna) {
  const form = formPara(cartao, coluna)
  if (coluna.dataset.dataDe) {
    const campo = document.getElementById(`campo-${coluna.dataset.dataDe}`)
    if (!campo.reportValidity()) return // vazia ou fora do mês: o navegador avisa no campo
    form.elements.conclusao_data.value = campo.value
  }
  // Volta ao quadro como está, com as datas escolhidas (o endereço acompanha os campos).
  form.elements.volta.value = location.pathname + location.search
  form.elements.status_id.value = coluna.dataset.coluna
  // O cartão já vai para a coluna nova enquanto a resposta não chega.
  coluna.querySelector('[data-cartoes]').append(cartao)
  form.requestSubmit()
}

document.addEventListener('dragstart', (e) => {
  const cartao = e.target.closest?.('[data-cartao]')
  if (!cartao?.draggable) return
  arrastado = cartao
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', '') // sem dado, o Firefox não começa a arrastar
  cartao.classList.add('opacity-50')
})
document.addEventListener('dragend', () => {
  arrastado?.classList.remove('opacity-50')
  arrastado = null
  destacar(null)
})
document.addEventListener('dragover', (e) => {
  const coluna = e.target.closest?.('[data-coluna]')
  const pode = arrastado && coluna && formPara(arrastado, coluna)
  destacar(pode ? coluna : null)
  if (pode) e.preventDefault() // aceita o soltar
})
document.addEventListener('drop', (e) => {
  const coluna = e.target.closest?.('[data-coluna]')
  if (!arrastado || !coluna || !formPara(arrastado, coluna)) return
  e.preventDefault()
  enviar(arrastado, coluna)
})

// As datas do topo não recarregam o quadro (os campos de data não aplicam ao mudar, app.js):
// só vão para o endereço, para o quadro voltar com elas depois de cada mudança.
document.addEventListener('change', (e) => {
  if (!['concluir_em', 'cancelar_em'].includes(e.target.name)) return
  const url = new URL(location.href)
  url.searchParams.set(e.target.name, e.target.value)
  history.replaceState(null, '', url)
})
