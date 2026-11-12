// Agenda (templates/agenda/index.html). JavaScript puro, sem build (ADR 0011).
//
// - A grade de horas abre rolada até a hora marcada com data-rolar-ate (7h ou o primeiro
//   compromisso do dia).
// - No dia, arrastar a borda de cima (data-alca="inicio") ou a de baixo ("fim") de um compromisso
//   muda o início ou o fim, de 15 em 15 minutos; ao soltar, o #form-horario envia o novo horário
//   e a página volta atualizada. Sem JavaScript, o horário muda pela janela do compromisso.

const PASSO = 15
const dois = (n) => String(n).padStart(2, '0')
const hora = (minutos) => `${dois(Math.floor(minutos / 60) % 24)}:${dois(minutos % 60)}`

const grade = document.querySelector('[data-grade]')
const alvo = grade?.querySelector('[data-rolar-ate]')
if (alvo) grade.scrollTop = alvo.offsetTop

let arrasto = null

function desenhar({ item, inicio, fim, de, ate }) {
  item.style.top = `${((inicio - de) / (ate - de)) * 100}%`
  item.style.height = `${((fim - inicio) / (ate - de)) * 100}%`
  item.querySelector('[data-horario]').textContent = `${hora(inicio)} – ${hora(fim)}`
}

document.addEventListener('pointerdown', (e) => {
  const alca = e.target.closest?.('[data-alca]')
  if (!alca || e.button !== 0) return
  e.preventDefault()
  const item = alca.closest('[data-compromisso]')
  const coluna = item.closest('[data-dia]')
  arrasto = {
    borda: alca.dataset.alca,
    item,
    coluna,
    inicio: Number(item.dataset.inicio),
    fim: Number(item.dataset.fim),
    de: Number(coluna.dataset.de) * 60,
    ate: Number(coluna.dataset.ate) * 60,
    mudou: false,
  }
  alca.setPointerCapture(e.pointerId)
  document.body.classList.add('cursor-ns-resize', 'select-none')
})

document.addEventListener('pointermove', (e) => {
  if (!arrasto) return
  const { coluna, de, ate } = arrasto
  const caixa = coluna.getBoundingClientRect()
  const minutos = de + Math.round((((e.clientY - caixa.top) / caixa.height) * (ate - de)) / PASSO) * PASSO
  const limitado = Math.max(de, Math.min(ate, minutos))
  // Pelo menos 15 minutos: uma borda não passa da outra.
  if (arrasto.borda === 'inicio') arrasto.inicio = Math.min(limitado, arrasto.fim - PASSO)
  else arrasto.fim = Math.max(limitado, arrasto.inicio + PASSO)
  arrasto.mudou = arrasto.inicio !== Number(arrasto.item.dataset.inicio) || arrasto.fim !== Number(arrasto.item.dataset.fim)
  desenhar(arrasto)
})

function soltar(e) {
  if (!arrasto) return
  const { item, inicio, fim, mudou } = arrasto
  // Cancelado pelo navegador: volta ao horário de antes, sem gravar.
  if (e.type === 'pointercancel') {
    desenhar({ ...arrasto, inicio: Number(item.dataset.inicio), fim: Number(item.dataset.fim) })
    arrasto = null
    document.body.classList.remove('cursor-ns-resize', 'select-none')
    return
  }
  arrasto = null
  document.body.classList.remove('cursor-ns-resize', 'select-none')
  // O clique que o navegador manda logo depois de soltar não abre a janela do compromisso.
  const engolir = (clique) => {
    clique.preventDefault()
    clique.stopImmediatePropagation()
  }
  addEventListener('click', engolir, { capture: true, once: true })
  setTimeout(() => removeEventListener('click', engolir, { capture: true }))
  if (!mudou) return
  const form = document.getElementById('form-horario')
  form.action = `/agenda/${item.dataset.compromisso}/horario`
  form.elements.inicio.value = inicio
  form.elements.fim.value = fim
  form.requestSubmit()
}
document.addEventListener('pointerup', soltar)
document.addEventListener('pointercancel', soltar)
