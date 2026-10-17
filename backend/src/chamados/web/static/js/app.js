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
