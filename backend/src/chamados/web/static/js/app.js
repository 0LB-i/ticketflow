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

// Avisos (docs/13 §13.6): os de sucesso somem em 5 s, contados de novo depois que o mouse e o
// foco saem deles (dá tempo de ler); todos fecham pelo X.
document.addEventListener('click', (e) => {
  e.target.closest('[data-fecha-aviso]')?.closest('[data-aviso]').remove()
})
for (const aviso of document.querySelectorAll('[data-aviso="success"]')) {
  let espera
  let mouse = false
  let foco = false
  const contar = () => {
    clearTimeout(espera)
    if (!mouse && !foco) espera = setTimeout(() => aviso.remove(), 5000)
  }
  aviso.addEventListener('mouseenter', () => {
    mouse = true
    contar()
  })
  aviso.addEventListener('mouseleave', () => {
    mouse = false
    contar()
  })
  aviso.addEventListener('focusin', () => {
    foco = true
    contar()
  })
  aviso.addEventListener('focusout', (e) => {
    foco = aviso.contains(e.relatedTarget)
    contar()
  })
  contar()
}

// Envio duplo (duplo clique em Registrar, Comentar…): enquanto a resposta não chega, o
// formulário não sai de novo e os botões de envio dele (também os de fora, com form="id") ficam
// esmaecidos. A trava solta sozinha em 5 s, para quem parou o envio (Esc, botão Parar) poder
// enviar de novo sem recarregar. O ouvinte fica na window: roda depois dos do document, então
// não prende o formulário que um deles segurou (o chamado.js espera os anexos subirem).
const destravar = new WeakMap()
function travar(form, travado) {
  clearTimeout(destravar.get(form))
  if (travado) destravar.set(form, setTimeout(() => travar(form, false), 5000))
  form.toggleAttribute('data-travado', travado)
  for (const botao of form.elements) {
    if (botao.type !== 'submit') continue
    if (travado) botao.setAttribute('aria-disabled', 'true')
    else botao.removeAttribute('aria-disabled')
  }
}
addEventListener('submit', (e) => {
  const form = e.target
  if (form.method !== 'post') return
  if ('travado' in form.dataset) e.preventDefault()
  else if (!e.defaultPrevented) travar(form, true)
})
// Ao voltar para a página (cache do navegador), o formulário pode ser enviado de novo.
addEventListener('pageshow', () => {
  for (const form of document.querySelectorAll('form[data-travado]')) travar(form, false)
})

// Formulários de filtro: aplicam ao escolher uma opção. Datas não: o Chrome dispara o change a
// cada parte digitada (vão com o botão Aplicar ou o Enter). As etiquetas aplicam no chamado.js,
// depois de entrar no formulário.
document.addEventListener('change', (e) => {
  const form = e.target.form
  if (!form?.matches('[data-envia-ao-mudar]') || e.target.type === 'date') return
  if (!e.target.matches('[data-chips-adiciona]')) form.requestSubmit()
})

// Cadastro de usuário: os campos que dependem do papel (a empresa do Cliente; os grupos dos
// outros). Os de outro papel ficam num <fieldset disabled>, que o navegador não valida nem envia.
document.addEventListener('change', (e) => {
  if (e.target.name !== 'role' || !e.target.form?.matches('[data-por-papel]')) return
  for (const el of e.target.form.querySelectorAll('[data-se-papel]')) {
    el.hidden = el.disabled = !el.dataset.sePapel.split(' ').includes(e.target.value)
  }
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

// Calendário e listas de horários: os campos de data e hora continuam os nativos (digitar e o
// valor enviado não mudam), mas a janela que abre é a nossa, porque a do navegador não aceita
// CSS. Abre com o clique, Alt+↓ ou F4; o tempo gasto (data-sugestoes, os horários sugeridos)
// também com ↓. A janela é um popover (camada de cima, também sobre os <dialog>), centralizada
// sob o campo; Esc e o clique fora fecham. Na tela de toque fica a janela do sistema.
const usaJanelas = 'showPopover' in HTMLElement.prototype && matchMedia('(pointer: fine)').matches
const CAMPO_COM_JANELA = 'input[type=date], input[type=time], input[data-sugestoes]'
const HORARIOS = Array.from({ length: 48 }, (_, i) => `${String(i >> 1).padStart(2, '0')}:${i % 2 ? '30' : '00'}`)
let janelaAberta = null // { campo, janela }
let cliqueFecha = false

const idiomaDaPagina = document.documentElement.lang || 'pt-BR'
const textoMes = new Intl.DateTimeFormat(idiomaDaPagina, { month: 'long', year: 'numeric' })
const textoDia = new Intl.DateTimeFormat(idiomaDaPagina, { dateStyle: 'full' })
const textoSemana = new Intl.DateTimeFormat(idiomaDaPagina, { weekday: 'short' })

const isoDoDia = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
function diaDoIso(iso) {
  const [ano, mes, dia] = iso.split('-').map(Number)
  return new Date(ano, mes - 1, dia)
}
// "Hoje" no fuso da empresa (data-fuso), como o campo de data e hora do chamado.
const hojeNoFuso = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: document.documentElement.dataset.fuso || undefined }).format(new Date())

function posicionarJanela() {
  if (!janelaAberta) return
  const c = janelaAberta.campo.getBoundingClientRect()
  const j = janelaAberta.janela.getBoundingClientRect()
  const esquerda = Math.max(8, Math.min(c.left + (c.width - j.width) / 2, innerWidth - j.width - 8))
  // Sem espaço embaixo, abre em cima do campo.
  const embaixo = c.bottom + 4 + j.height <= innerHeight - 8 || c.top - 4 - j.height < 8
  janelaAberta.janela.style.left = `${esquerda}px`
  janelaAberta.janela.style.top = `${embaixo ? c.bottom + 4 : c.top - 4 - j.height}px`
}

function abrirJanela(campo, janela) {
  janelaAberta?.janela.hidePopover()
  janela.popover = 'auto'
  janela.tabIndex = -1 // o clique num ponto sem botão deixa o foco na janela
  janela.addEventListener('beforetoggle', (e) => {
    // Fechada com o foco dentro (Esc, escolha): o foco volta ao campo.
    if (e.newState === 'closed' && janela.contains(document.activeElement)) campo.focus()
  })
  janela.addEventListener('toggle', (e) => {
    if (e.newState !== 'closed') return
    janela.remove()
    if (janelaAberta?.janela === janela) janelaAberta = null
  })
  // Ao lado do campo: dentro de um <dialog> aberto, o resto da página não recebe cliques.
  campo.after(janela)
  janela.showPopover()
  janelaAberta = { campo, janela }
  posicionarJanela()
}

function escolherValor(campo, valor) {
  campo.value = valor
  campo.dispatchEvent(new Event('input', { bubbles: true }))
  campo.dispatchEvent(new Event('change', { bubbles: true }))
  janelaAberta?.janela.hidePopover()
  campo.focus()
}

const seta = (d) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-4" aria-hidden="true"><path d="${d}"/></svg>`

/** Mostra o mês de `dia` e, com `focar`, põe o foco nesse dia. */
function desenharCalendario(janela, campo, dia, focar = false) {
  const mes = new Date(dia.getFullYear(), dia.getMonth(), 1)
  const inicio = new Date(mes.getFullYear(), mes.getMonth(), 1 - mes.getDay())
  const diasNoMes = new Date(mes.getFullYear(), mes.getMonth() + 1, 0).getDate()
  const hoje = hojeNoFuso()
  const alvo = isoDoDia(dia)
  janela.dataset.mes = isoDoDia(mes)
  janela.querySelector('[data-titulo]').textContent = textoMes.format(mes)
  let linhas = ''
  for (let semana = 0; semana < Math.ceil((mes.getDay() + diasNoMes) / 7); semana++) {
    linhas += '<tr>'
    for (let i = 0; i < 7; i++) {
      const d = new Date(inicio.getFullYear(), inicio.getMonth(), inicio.getDate() + semana * 7 + i)
      const iso = isoDoDia(d)
      const escolhido = iso === campo.value
      const fora = (campo.min && iso < campo.min) || (campo.max && iso > campo.max)
      const cor = escolhido
        ? 'bg-primary font-medium text-on-primary hover:bg-primary-hover'
        : iso === hoje
          ? 'font-semibold text-primary hover:bg-surface-raised'
          : d.getMonth() !== mes.getMonth()
            ? 'text-muted hover:bg-surface-raised'
            : 'hover:bg-surface-raised'
      linhas += `<td role="gridcell" aria-selected="${escolhido}"><button type="button" data-dia="${iso}" tabindex="${iso === alvo ? 0 : -1}" aria-label="${textoDia.format(d)}"${iso === hoje ? ' aria-current="date"' : ''}${fora ? ' disabled' : ''} class="size-9 rounded-md tabular-nums disabled:cursor-not-allowed disabled:opacity-40 ${cor}">${d.getDate()}</button></td>`
    }
    linhas += '</tr>'
  }
  janela.querySelector('tbody').innerHTML = linhas
  if (focar) janela.querySelector(`[data-dia="${alvo}"]`)?.focus()
}

function abrirCalendario(campo, focar) {
  const janela = document.createElement('div')
  janela.className = 'fixed inset-auto m-0 rounded-lg border border-border bg-surface p-2 text-fg shadow-lg'
  const semana = Array.from({ length: 7 }, (_, i) => {
    const nome = textoSemana.format(new Date(2026, 0, 4 + i)).replace('.', '')
    return `<th scope="col" class="size-9 text-xs font-normal text-muted">${nome}</th>`
  })
  janela.innerHTML = `
    <div class="flex items-center justify-between gap-2 pb-1">
      <button type="button" data-muda-mes="-1" class="inline-flex size-8 items-center justify-center rounded-md text-muted hover:bg-surface-raised hover:text-fg">${seta('m15 18-6-6 6-6')}</button>
      <span data-titulo aria-live="polite" class="font-medium first-letter:uppercase"></span>
      <button type="button" data-muda-mes="1" class="inline-flex size-8 items-center justify-center rounded-md text-muted hover:bg-surface-raised hover:text-fg">${seta('m9 18 6-6-6-6')}</button>
    </div>
    <table role="grid" class="border-collapse"><thead><tr>${semana.join('')}</tr></thead><tbody></tbody></table>`
  const [anterior, proximo] = janela.querySelectorAll('[data-muda-mes]')
  anterior.setAttribute('aria-label', document.body.dataset.mesAnterior)
  proximo.setAttribute('aria-label', document.body.dataset.proximoMes)

  janela.addEventListener('click', (e) => {
    const muda = e.target.closest('[data-muda-mes]')
    if (muda) {
      const mes = diaDoIso(janela.dataset.mes)
      desenharCalendario(janela, campo, new Date(mes.getFullYear(), mes.getMonth() + Number(muda.dataset.mudaMes), 1))
    }
    const dia = e.target.closest('[data-dia]')
    if (dia) escolherValor(campo, dia.dataset.dia)
  })
  // Setas: dia a dia e semana a semana; Page Up/Down: mês a mês.
  janela.addEventListener('keydown', (e) => {
    const atual = e.target.closest('[data-dia]')
    if (!atual) return
    const d = diaDoIso(atual.dataset.dia)
    const passo = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key]
    let novo
    if (passo) novo = new Date(d.getFullYear(), d.getMonth(), d.getDate() + passo)
    else if (e.key === 'PageUp' || e.key === 'PageDown') {
      const mes = d.getMonth() + (e.key === 'PageUp' ? -1 : 1)
      novo = new Date(d.getFullYear(), mes, Math.min(d.getDate(), new Date(d.getFullYear(), mes + 1, 0).getDate()))
    } else return
    e.preventDefault()
    const iso = isoDoDia(novo)
    if ((campo.min && iso < campo.min) || (campo.max && iso > campo.max)) return
    desenharCalendario(janela, campo, novo, true)
  })

  abrirJanela(campo, janela)
  desenharCalendario(janela, campo, campo.value ? diaDoIso(campo.value) : diaDoIso(hojeNoFuso()), focar)
  posicionarJanela()
}

function abrirLista(campo, valores, focar) {
  const lista = document.createElement('ul')
  lista.setAttribute('role', 'listbox')
  const rotulo = campo.labels?.[0]?.textContent.trim() || campo.getAttribute('aria-label')
  if (rotulo) lista.setAttribute('aria-label', rotulo)
  lista.className = 'fixed inset-auto m-0 max-h-72 overflow-y-auto rounded-lg border border-border bg-surface p-1 text-fg shadow-lg'
  lista.style.minWidth = `${campo.offsetWidth}px`
  for (const valor of valores) {
    const item = document.createElement('li')
    item.setAttribute('role', 'option')
    item.setAttribute('aria-selected', String(valor === campo.value))
    item.tabIndex = -1
    item.dataset.valor = item.textContent = valor
    item.className =
      'flex cursor-default rounded px-2 py-1.5 tabular-nums select-none hover:bg-surface-raised focus:bg-surface-raised focus:outline-none aria-selected:font-medium aria-selected:text-primary'
    lista.append(item)
  }
  lista.addEventListener('click', (e) => {
    const item = e.target.closest('[role=option]')
    if (item) escolherValor(campo, item.dataset.valor)
  })
  lista.addEventListener('keydown', (e) => {
    const item = e.target.closest('[role=option]')
    if (!item) return
    const destino = {
      ArrowDown: item.nextElementSibling,
      ArrowUp: item.previousElementSibling,
      Home: lista.firstElementChild,
      End: lista.lastElementChild,
    }[e.key]
    if (destino !== undefined) {
      e.preventDefault()
      destino?.focus()
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      escolherValor(campo, item.dataset.valor)
    }
  })

  abrirJanela(campo, lista)
  // A lista começa no horário do campo (ou no seguinte).
  const atual = [...lista.children].find((i) => i.dataset.valor >= campo.value) ?? lista.lastElementChild
  if (!atual) return
  lista.scrollTop = atual.offsetTop - (lista.clientHeight - atual.offsetHeight) / 2
  if (focar) atual.focus()
}

function abrirJanelaDoCampo(campo, focar) {
  if (campo.type === 'date') abrirCalendario(campo, focar)
  else if (campo.type === 'time') abrirLista(campo, HORARIOS, focar)
  else abrirLista(campo, [...document.getElementById(campo.dataset.sugestoes).options].map((o) => o.value), focar)
}

if (usaJanelas) {
  // O <datalist> do navegador sai; os horários dele vão para a nossa lista.
  htmx.onLoad((raiz) => {
    for (const campo of raiz.querySelectorAll('input[data-sugestoes][list]')) {
      campo.dataset.sugestoes = campo.getAttribute('list')
      campo.removeAttribute('list')
    }
  })
  // Clique no campo com a janela aberta: o clique fora já a fechou, e ela não abre de novo.
  document.addEventListener('pointerdown', (e) => (cliqueFecha = e.target === janelaAberta?.campo), true)
  document.addEventListener('click', (e) => {
    const campo = e.target.closest?.(CAMPO_COM_JANELA)
    if (!campo || campo.disabled || campo.readOnly) return
    e.preventDefault() // o Firefox abre a janela dele ao clicar no campo
    if (cliqueFecha) cliqueFecha = false
    else abrirJanelaDoCampo(campo, false)
  })
  document.addEventListener('keydown', (e) => {
    const campo = e.target.closest?.(CAMPO_COM_JANELA)
    if (!campo || campo.readOnly) return
    const abre = e.key === 'ArrowDown' && (e.altKey || 'sugestoes' in campo.dataset)
    if (!abre && e.key !== 'F4') return
    e.preventDefault()
    abrirJanelaDoCampo(campo, true)
  })
  // Digitar no campo: o calendário vai para o mês digitado; a lista de horários fecha.
  document.addEventListener('input', (e) => {
    if (!e.isTrusted || e.target !== janelaAberta?.campo) return
    if (e.target.type !== 'date') janelaAberta.janela.hidePopover()
    else if (e.target.value) desenharCalendario(janelaAberta.janela, e.target, diaDoIso(e.target.value))
  })
  // Tab para fora fecha. Depois do evento: ao trocar o mês, o botão focado é refeito.
  document.addEventListener('focusout', () =>
    setTimeout(() => {
      if (!janelaAberta || !document.hasFocus()) return
      const ativo = document.activeElement
      if (ativo !== janelaAberta.campo && !janelaAberta.janela.contains(ativo)) janelaAberta.janela.hidePopover()
    }),
  )
  addEventListener('resize', posicionarJanela)
  addEventListener('scroll', posicionarJanela, true)
}
