// Comportamento comum das telas do servidor (ADR 0011): JavaScript puro, sem build.

// Menus em <details data-menu>: fecham ao clicar fora, ao escolher uma opção e com Esc.
document.addEventListener('click', (e) => {
  for (const menu of document.querySelectorAll('details[data-menu][open]')) {
    if (!menu.contains(e.target) || e.target.closest('[role^="menuitem"]')) menu.open = false
  }
})
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return
  for (const menu of document.querySelectorAll('details[data-menu][open]')) {
    menu.open = false
    menu.querySelector('summary').focus()
  }
})

// Tema claro, escuro ou automático (docs/17 §17.4). A escolha fica no navegador; o tema.js a
// aplica antes da primeira pintura.
const CHAVE_TEMA = 'tf-tema'
const sistemaEscuro = matchMedia('(prefers-color-scheme: dark)')

function temaSalvo() {
  try {
    return localStorage.getItem(CHAVE_TEMA) || 'automatico'
  } catch {
    return 'automatico' // armazenamento indisponível (modo privado)
  }
}

function aplicarTema(tema) {
  const escuro = tema === 'escuro' || (tema === 'automatico' && sistemaEscuro.matches)
  document.documentElement.classList.toggle('dark', escuro)
  for (const opcao of document.querySelectorAll('[data-tema]')) {
    opcao.setAttribute('aria-checked', String(opcao.dataset.tema === tema))
  }
}

document.addEventListener('click', (e) => {
  const opcao = e.target.closest('[data-tema]')
  if (!opcao) return
  try {
    localStorage.setItem(CHAVE_TEMA, opcao.dataset.tema)
  } catch {
    // sem persistência: o tema vale só nesta página
  }
  aplicarTema(opcao.dataset.tema)
})
sistemaEscuro.addEventListener('change', () => aplicarTema(temaSalvo()))
aplicarTema(temaSalvo())

// Diálogos nativos (<dialog>): o botão com data-abre-dialogo="id" abre; data-fecha-dialogo e o
// clique fora (no fundo escurecido) fecham. Esc o navegador já trata.
document.addEventListener('click', (e) => {
  const abre = e.target.closest('[data-abre-dialogo]')
  if (abre) document.getElementById(abre.dataset.abreDialogo).showModal()
  const fecha = e.target.closest('[data-fecha-dialogo]')
  if (fecha) fecha.closest('dialog').close()
  // No fundo, o alvo do clique é o próprio <dialog>, mas fora do retângulo dele.
  if (e.target instanceof HTMLDialogElement) {
    const r = e.target.getBoundingClientRect()
    const fora = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom
    if (fora) e.target.close()
  }
})

// Avisos (docs/13 §13.6): os de sucesso somem em 5 s; todos fecham pelo X.
document.addEventListener('click', (e) => {
  e.target.closest('[data-fecha-aviso]')?.closest('[data-aviso]').remove()
})
for (const aviso of document.querySelectorAll('[data-aviso="success"]')) {
  setTimeout(() => aviso.remove(), 5000)
}

// Formulários de filtro: aplicam ao escolher uma opção.
document.addEventListener('change', (e) => {
  const form = e.target.closest('form[data-envia-ao-mudar]')
  if (form) form.requestSubmit()
})

// Status em massa (lista de chamados): a janela do pé da tela aparece com a primeira seleção.
function atualizarSelecao() {
  const barra = document.getElementById('em-massa')
  if (!barra) return
  const caixas = [...document.querySelectorAll('[data-seleciona]')]
  const marcadas = caixas.filter((c) => c.checked).length
  barra.hidden = marcadas === 0
  const contagem = barra.querySelector('[data-contagem]')
  contagem.textContent = contagem.dataset.contagem.replace('{n}', marcadas)
  const todos = document.querySelector('[data-marca-todos]')
  if (todos) todos.checked = caixas.length > 0 && marcadas === caixas.length
  // Espaço no fim da página para a janela não cobrir as últimas linhas.
  document.querySelector('[data-em-massa-espaco]')?.classList.toggle('pb-28', marcadas > 0)
}
document.addEventListener('change', (e) => {
  if (e.target.matches('[data-marca-todos]')) {
    for (const caixa of document.querySelectorAll('[data-seleciona]')) caixa.checked = e.target.checked
  }
  if (e.target.matches('[data-marca-todos], [data-seleciona]')) atualizarSelecao()
})
document.addEventListener('click', (e) => {
  if (!e.target.closest('[data-limpa-selecao]')) return
  for (const caixa of document.querySelectorAll('[data-seleciona]')) caixa.checked = false
  atualizarSelecao()
})
// Linhas novas do "Carregar mais" chegam sem marcar: o "selecionar todos" deixa de valer.
document.addEventListener('htmx:afterSettle', atualizarSelecao)
// O navegador pode restaurar as caixas marcadas ao voltar para a página.
addEventListener('pageshow', atualizarSelecao)

// Painéis e janelas abertos pelo endereço (data-abre-ao-carregar): abrem quando a página ou o
// trecho trocado pelo HTMX chega; ao fechar, o endereço volta ao da lista (data-volta).
function abrirAoCarregar(raiz) {
  for (const janela of raiz.querySelectorAll('dialog[data-abre-ao-carregar]:not([open])')) {
    // Resposta de um POST (ex.: o link de acesso): o endereço passa a ser o da tela, para um
    // F5 não enviar de novo.
    if (janela.dataset.endereco) history.replaceState(null, '', janela.dataset.endereco)
    janela.showModal()
    if (janela.dataset.volta) {
      janela.addEventListener('close', () => history.replaceState(null, '', janela.dataset.volta))
    }
  }
}
htmx.onLoad(abrirAoCarregar)

// Copiar (o link de acesso para repassar quando não há e-mail configurado).
document.addEventListener('click', async (e) => {
  const botao = e.target.closest('[data-copia]')
  if (!botao) return
  const campo = document.getElementById(botao.dataset.copia)
  try {
    await navigator.clipboard.writeText(campo.value)
  } catch {
    // Sem permissão (ou sem HTTPS): o texto fica selecionado para o Ctrl+C.
    campo.select()
    return
  }
  const texto = botao.textContent
  botao.textContent = botao.dataset.copiado
  setTimeout(() => (botao.textContent = texto), 2000)
})
