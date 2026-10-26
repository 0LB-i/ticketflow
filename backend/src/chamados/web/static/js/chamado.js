// Campos das telas de chamado (templates/_fields.html): editor, anexos, tempo gasto, data e
// hora, pessoas e cliente. JavaScript puro, sem build (ADR 0011); o Tiptap vem empacotado em
// vendor/ (scripts/vendor-tiptap.sh) e fica no objeto global `Tiptap`.

const FUSO = document.querySelector('meta[name=fuso]')?.content || 'UTC'
const idioma = () => document.documentElement.lang || 'pt-BR'

function lerCookie(nome) {
  const achado = document.cookie.match(new RegExp(`(?:^|; )${nome}=([^;]*)`))
  return achado ? decodeURIComponent(achado[1]) : ''
}

/** 1ª etapa do envio de um anexo (docs/11 §11.4): o arquivo vai antes do formulário. */
async function enviarArquivo(arquivo) {
  const dados = new FormData()
  dados.append('file', arquivo)
  const resposta = await fetch('/api/v1/uploads', {
    method: 'POST',
    body: dados,
    headers: { 'X-CSRF-Token': lerCookie('tf_csrf'), 'Accept-Language': idioma() },
  })
  const corpo = await resposta.json().catch(() => ({}))
  if (!resposta.ok) throw new Error(corpo.detail || corpo.title || resposta.statusText)
  return corpo
}

function formatarTamanho(bytes) {
  const formato = new Intl.NumberFormat(idioma(), { maximumFractionDigits: 1 })
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${formato.format(bytes / 1024)} KB`
  return `${formato.format(bytes / 1024 / 1024)} MB`
}

const semAcento = (s) =>
  s
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()

// --- editor (Tiptap → Markdown) -------------------------------------------------------------

const editores = new WeakMap()

function pessoas() {
  const dados = document.getElementById('pessoas')
  return dados ? JSON.parse(dados.textContent) : []
}

/** Lista de sugestões do @, posicionada embaixo do cursor. */
function sugestoesDeMencao(caixa) {
  let lista = null
  let itens = []
  let ativo = 0
  let comando = null

  function desenhar() {
    lista.replaceChildren()
    if (!itens.length) {
      const vazio = document.createElement('li')
      vazio.className = 'px-2 py-1 text-muted'
      vazio.textContent = caixa.dataset.ninguem
      lista.append(vazio)
      return
    }
    itens.forEach((pessoa, i) => {
      const li = document.createElement('li')
      li.setAttribute('role', 'option')
      li.setAttribute('aria-selected', String(i === ativo))
      li.className =
        'cursor-pointer rounded px-2 py-1 ' +
        (i === ativo ? 'bg-primary-subtle text-primary' : 'hover:bg-surface-raised')
      li.textContent = pessoa.label
      li.addEventListener('mousedown', (e) => {
        e.preventDefault()
        comando(pessoa)
      })
      lista.append(li)
    })
  }

  function posicionar(props) {
    const rect = props.clientRect?.()
    if (!rect || !lista) return
    const esquerda = Math.min(rect.left, window.innerWidth - lista.offsetWidth - 8)
    Object.assign(lista.style, {
      position: 'fixed',
      left: `${Math.max(8, esquerda)}px`,
      top: `${rect.bottom + 4}px`,
      zIndex: '50',
    })
  }

  function atualizar(props) {
    itens = props.items
    comando = props.command
    ativo = Math.min(ativo, Math.max(0, itens.length - 1))
    desenhar()
    posicionar(props)
  }

  return {
    onStart(props) {
      lista = document.createElement('ul')
      lista.setAttribute('role', 'listbox')
      lista.setAttribute('aria-label', caixa.dataset.mencionar)
      lista.className =
        'max-h-60 min-w-48 overflow-y-auto rounded-md border border-border bg-surface p-1 text-fg shadow-lg'
      document.body.append(lista)
      ativo = 0
      atualizar(props)
    },
    onUpdate: atualizar,
    onKeyDown({ event }) {
      const n = itens.length
      if (event.key === 'Escape' || !n) return false
      if (event.key === 'ArrowDown') ativo = (ativo + 1) % n
      else if (event.key === 'ArrowUp') ativo = (ativo + n - 1) % n
      else if (event.key === 'Enter' || event.key === 'Tab') comando(itens[ativo])
      else return false
      desenhar()
      return true
    },
    onExit() {
      lista?.remove()
      lista = null
    },
  }
}

function criarEditor(caixa) {
  const { Editor, StarterKit, Markdown, Placeholder, Mention, Image } = window.Tiptap
  const texto = caixa.querySelector('textarea')
  const area = caixa.querySelector('[data-editor-area]')
  const enviando = caixa.querySelector('[data-editor-enviando]')
  const erro = caixa.querySelector('[data-editor-erro]')
  let imagensSubindo = 0

  const extensoes = [
    StarterKit.configure({ heading: { levels: [2, 3] }, link: { openOnClick: false } }),
    Markdown,
    Placeholder.configure({ placeholder: caixa.dataset.placeholder || '' }),
  ]
  if ('mencoes' in caixa.dataset) {
    const colegas = pessoas()
    extensoes.push(
      Mention.extend({ renderMarkdown: (node) => `@${node.attrs?.label ?? ''}` }).configure({
        HTMLAttributes: { class: 'mencao' },
        renderText: ({ node }) => `@${node.attrs.label}`,
        suggestion: {
          items: ({ query }) =>
            colegas.filter((p) => semAcento(p.label).includes(semAcento(query))).slice(0, 8),
          render: () => sugestoesDeMencao(caixa),
        },
      }),
    )
  }
  const anexar = 'anexar' in caixa.dataset
  if (anexar) extensoes.push(Image)

  const imagens = (arquivos) => [...(arquivos ?? [])].filter((f) => f.type.startsWith('image/'))

  async function inserirImagens(arquivos) {
    erro.hidden = true
    for (const arquivo of arquivos) {
      imagensSubindo++
      caixa.dataset.subindo = String(imagensSubindo)
      atualizarBotoes(caixa.closest('form'))
      enviando.hidden = false
      try {
        const anexo = await enviarArquivo(arquivo)
        editor
          .chain()
          .focus()
          .setImage({ src: `/api/v1/attachments/${anexo.id}`, alt: anexo.filename })
          .run()
      } catch (e) {
        erro.textContent = e.message
        erro.hidden = false
      } finally {
        imagensSubindo--
        enviando.hidden = imagensSubindo === 0
        caixa.dataset.subindo = String(imagensSubindo)
        atualizarBotoes(caixa.closest('form'))
      }
    }
  }

  const editor = new Editor({
    element: area,
    content: texto.value,
    contentType: 'markdown',
    extensions: extensoes,
    editorProps: {
      attributes: {
        id: caixa.dataset.id,
        class: `texto-formatado ${'alto' in caixa.dataset ? 'min-h-80' : 'min-h-24'} px-3 py-2 outline-none`,
        role: 'textbox',
        'aria-multiline': 'true',
        'aria-labelledby': `${caixa.dataset.id}-rotulo`,
      },
      handlePaste: (_view, evento) => {
        const lista = imagens(evento.clipboardData?.files)
        if (!anexar || !lista.length) return false
        inserirImagens(lista)
        return true
      },
      handleDrop: (view, evento) => {
        const lista = imagens(evento.dataTransfer?.files)
        if (!anexar || !lista.length) return false
        const destino = view.posAtCoords({ left: evento.clientX, top: evento.clientY })
        if (destino) editor.commands.setTextSelection(destino.pos)
        inserirImagens(lista)
        return true
      },
    },
    onUpdate: () => {
      texto.value = editor.isEmpty ? '' : editor.getMarkdown()
      atualizarBotoes(caixa.closest('form'))
    },
    onTransaction: () => {
      for (const botao of caixa.querySelectorAll('[data-comando]')) {
        botao.setAttribute('aria-pressed', String(editor.isActive(botao.dataset.marca)))
      }
    },
  })
  editores.set(caixa, editor)

  for (const botao of caixa.querySelectorAll('[data-comando]')) {
    botao.addEventListener('click', () => editor.chain().focus()[botao.dataset.comando]().run())
  }
  caixa.querySelector('label').addEventListener('click', (e) => {
    e.preventDefault()
    editor.commands.focus()
  })
  // O editor substitui o <textarea>, que continua levando o texto no formulário.
  caixa.querySelector('[data-editor-caixa]').hidden = false
  texto.hidden = true
  caixa.dataset.pronto = ''
}

/**
 * Ids das pessoas mencionadas. O texto guarda só "@Nome": quando o formulário volta com erro,
 * o editor recomeça do Markdown e as menções viram texto, por isso "@Nome" de um colega
 * também conta.
 */
function mencionados(caixa) {
  const ids = new Set()
  editores.get(caixa)?.state.doc.descendants((node) => {
    if (node.type.name === 'mention' && node.attrs.id) ids.add(String(node.attrs.id))
  })
  const texto = caixa.querySelector('textarea').value
  for (const pessoa of pessoas()) {
    if (texto.includes(`@${pessoa.label}`)) ids.add(pessoa.id)
  }
  return [...ids]
}

/** Arquivo ainda subindo (anexo ou imagem colada): o formulário espera. */
function subindo(form) {
  return (
    !!form.querySelector('[data-item][data-enviando]') ||
    [...form.querySelectorAll('[data-editor]')].some((c) => Number(c.dataset.subindo || 0) > 0)
  )
}

/** Os botões de envio esperam os arquivos; "Adicionar tarefa" e "Salvar", também o texto. */
function atualizarBotoes(form) {
  if (!form) return
  const ocupado = subindo(form)
  const vazio = [...form.querySelectorAll('[data-editor] textarea')].every((t) => !t.value.trim())
  const botoes = [...form.querySelectorAll('button[type=submit]')]
  if (form.id) botoes.push(...document.querySelectorAll(`button[type=submit][form="${form.id}"]`))
  for (const botao of botoes) {
    botao.disabled = ocupado || ('exigeTexto' in botao.dataset && vazio)
  }
}

htmx.onLoad((raiz) => {
  if (!window.Tiptap) return
  for (const caixa of raiz.querySelectorAll('[data-editor]:not([data-pronto])')) criarEditor(caixa)
  for (const form of raiz.querySelectorAll('form')) atualizarBotoes(form)
})

// No envio: os ids das menções vão junto; com arquivo ainda subindo, o formulário espera.
document.addEventListener('submit', (e) => {
  const form = e.target
  if (subindo(form)) {
    e.preventDefault()
    return
  }
  form.querySelectorAll('input[name="mention_ids"]').forEach((i) => i.remove())
  for (const caixa of form.querySelectorAll('[data-editor]')) {
    for (const id of mencionados(caixa)) {
      const campo = document.createElement('input')
      Object.assign(campo, { type: 'hidden', name: 'mention_ids', value: id })
      form.append(campo)
    }
  }
})

// --- anexos ---------------------------------------------------------------------------------

function adicionarArquivos(anexador, arquivos) {
  const aviso = anexador.querySelector('[data-aviso]')
  const lista = anexador.querySelector('[data-lista]')
  const modelo = anexador.querySelector('template[data-modelo]')
  const max = Number(anexador.dataset.max)
  aviso.hidden = true
  for (const arquivo of arquivos) {
    if (lista.querySelectorAll('[data-item]:not([data-falhou])').length >= max) {
      aviso.textContent = anexador.dataset.demais
      aviso.hidden = false
      break
    }
    const item = modelo.content.firstElementChild.cloneNode(true)
    item.dataset.enviando = ''
    item.querySelector('[data-nome]').textContent = arquivo.name
    item.querySelector('[data-tamanho]').textContent = formatarTamanho(arquivo.size)
    const remover = item.querySelector('[data-remove-item]')
    remover.setAttribute('aria-label', remover.dataset.rotulo.replace('{nome}', arquivo.name))
    lista.append(item)
    atualizarBotoes(anexador.closest('form'))
    enviarArquivo(arquivo)
      .then((anexo) => {
        const campo = document.createElement('input')
        Object.assign(campo, { type: 'hidden', name: 'attachment_ids', value: anexo.id })
        item.append(campo)
        item.querySelector('[data-icone-pronto]').hidden = false
      })
      .catch((e) => {
        item.dataset.falhou = ''
        const erro = item.querySelector('[data-erro]')
        erro.textContent = e.message
        erro.hidden = false
        item.querySelector('[data-icone-pronto]').hidden = false
      })
      .finally(() => {
        delete item.dataset.enviando
        item.querySelector('[data-icone-enviando]').hidden = true
        atualizarBotoes(anexador.closest('form'))
      })
  }
}

document.addEventListener('click', (e) => {
  const escolher = e.target.closest('[data-escolhe-arquivo]')
  if (escolher) escolher.closest('[data-anexador]').querySelector('input[type=file]').click()
  const item = e.target.closest('[data-remove-item]')?.closest('[data-item]')
  if (item) {
    const form = item.closest('form')
    item.remove()
    atualizarBotoes(form)
  }
})
document.addEventListener('change', (e) => {
  if (!e.target.matches('[data-anexador] input[type=file]')) return
  adicionarArquivos(e.target.closest('[data-anexador]'), e.target.files)
  e.target.value = ''
})
for (const tipo of ['dragover', 'dragleave', 'drop']) {
  document.addEventListener(tipo, (e) => {
    const anexador = e.target.closest?.('[data-anexador]')
    if (!anexador) return
    e.preventDefault()
    const dentro = tipo === 'dragover'
    anexador.classList.toggle('border-primary', dentro)
    anexador.classList.toggle('bg-primary-subtle', dentro)
    if (tipo === 'drop') adicionarArquivos(anexador, e.dataTransfer.files)
  })
}

// --- tempo gasto (hh:mm) --------------------------------------------------------------------

/** Os números entram pela direita, como numa calculadora ("130" → "01:30"). */
function mascararHoraMinuto(texto) {
  const numeros = texto.replace(/\D/g, '').replace(/^0+/, '').slice(-4)
  if (!numeros) return ''
  const n = numeros.padStart(4, '0')
  return `${n.slice(0, 2)}:${n.slice(2)}`
}

document.addEventListener('input', (e) => {
  if (!e.target.matches('[data-duracao]')) return
  // Um horário escolhido na lista já vem no formato.
  if (/^\d{2}:\d{2}$/.test(e.target.value)) return
  e.target.value = mascararHoraMinuto(e.target.value)
})

// --- data e hora ----------------------------------------------------------------------------

const partes = new Intl.DateTimeFormat('en-CA', {
  timeZone: FUSO,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

function agoraNoFuso() {
  const p = Object.fromEntries(partes.formatToParts(new Date()).map((x) => [x.type, x.value]))
  return { data: `${p.year}-${p.month}-${p.day}`, hora: `${p.hour}:${p.minute}` }
}

/** Sem ajuste à mão, o campo mostra a hora atual, que vai andando. */
function acompanharRelogio() {
  const agora = agoraNoFuso()
  for (const campo of document.querySelectorAll('[data-data-hora]')) {
    campo.querySelector('input[type=date]').max = agora.data
    if (campo.querySelector('input[type=hidden]').value === '1') continue
    campo.querySelector('input[type=date]').value = agora.data
    campo.querySelector('input[type=time]').value = agora.hora
  }
}
acompanharRelogio()
setInterval(acompanharRelogio, 10_000)
document.addEventListener('htmx:afterSettle', acompanharRelogio)

function marcarAjuste(campo, ajustado) {
  campo.querySelector('input[type=hidden]').value = ajustado ? '1' : '0'
  campo.querySelector('[data-agora]').disabled = !ajustado
  campo.querySelector('[data-ajustado]').hidden = !ajustado
}
document.addEventListener('input', (e) => {
  const campo = e.target.closest('[data-data-hora]')
  if (campo && e.target.matches('input[type=date], input[type=time]')) marcarAjuste(campo, true)
})
document.addEventListener('click', (e) => {
  const agora = e.target.closest('[data-agora]')
  if (!agora) return
  marcarAjuste(agora.closest('[data-data-hora]'), false)
  acompanharRelogio()
})

// --- pessoas em etiquetas -------------------------------------------------------------------

function opcoesLivres(select) {
  return [...select.options].filter((o) => o.value && o.value !== '*' && !o.hidden)
}

function atualizarTodos(select) {
  const todos = [...select.options].find((o) => o.value === '*')
  if (todos) todos.hidden = todos.disabled = opcoesLivres(select).length === 0
}

// Num formulário de filtro (relatórios), pôr ou tirar uma etiqueta aplica na hora. O foco fica na
// lista da caixa (o × tirado sai da página), e a tela nova o devolve a ela pelo id.
function aplicarFiltro(caixa) {
  const form = caixa.closest('form[data-envia-ao-mudar]')
  if (!form) return
  caixa.querySelector('[data-chips-adiciona], [role=combobox]').focus()
  form.requestSubmit()
}

function adicionarEtiqueta(caixa, valor, nome) {
  const modelo = caixa.querySelector('template[data-modelo]')
  const etiqueta = modelo.content.firstElementChild.cloneNode(true)
  etiqueta.dataset.valor = valor
  etiqueta.querySelector('[data-rotulo]').textContent = nome
  etiqueta.querySelector('input').value = valor
  const remover = etiqueta.querySelector('[data-chips-remove]')
  remover.setAttribute('aria-label', remover.getAttribute('aria-label').replace('{nome}', nome))
  caixa.querySelector('[data-chips-lista]').append(etiqueta)
}

document.addEventListener('change', (e) => {
  if (!e.target.matches('[data-chips-adiciona]')) return
  const select = e.target
  const caixa = select.closest('[data-chips]')
  const escolhidas =
    select.value === '*' ? opcoesLivres(select) : [select.selectedOptions[0]].filter(Boolean)
  for (const opcao of escolhidas) {
    adicionarEtiqueta(caixa, opcao.value, opcao.textContent.trim())
    opcao.hidden = opcao.disabled = true
  }
  select.value = ''
  atualizarTodos(select)
  aplicarFiltro(caixa)
})
document.addEventListener('click', (e) => {
  const remover = e.target.closest('[data-chips-remove]')
  if (!remover) return
  const etiqueta = remover.closest('[data-valor]')
  const caixa = remover.closest('[data-chips]')
  // Na busca de cliente não há select: as opções vêm de novo do servidor, sem os escolhidos.
  const select = caixa.querySelector('[data-chips-adiciona]')
  const opcao = [...(select?.options ?? [])].find((o) => o.value === etiqueta.dataset.valor)
  if (opcao) opcao.hidden = opcao.disabled = false
  etiqueta.remove()
  if (select) atualizarTodos(select)
  aplicarFiltro(caixa)
})
htmx.onLoad((raiz) => raiz.querySelectorAll('[data-chips-adiciona]').forEach(atualizarTodos))

// --- relatórios (reports/index.html) --------------------------------------------------------

// O formulário aplica pelo HTMX esperando as escolhas seguidas. Uma resposta que chega depois de
// outra escolha (ainda no intervalo de espera) não troca a tela: apagaria a escolha nova; o
// pedido dela vem em seguida.
document.addEventListener('submit', (e) => {
  e.target.dataset.envios = String(Number(e.target.dataset.envios || 0) + 1)
}, true)
document.addEventListener('htmx:beforeRequest', (e) => {
  if (e.detail.target?.id !== 'relatorio') return
  e.detail.xhr.envios = e.detail.elt.dataset.envios
  e.detail.target.setAttribute('aria-busy', 'true')
})
document.addEventListener('htmx:beforeSwap', (e) => {
  // O `elt` do beforeSwap é o alvo (o #relatorio); quem pediu é o `requestConfig.elt`.
  const { xhr, requestConfig } = e.detail
  if (xhr.envios !== undefined && xhr.envios !== requestConfig.elt.dataset.envios) {
    e.detail.shouldSwap = false
  }
})
document.addEventListener('htmx:afterRequest', (e) => {
  if (e.detail.target?.id === 'relatorio') e.detail.target.removeAttribute('aria-busy')
})
// Avisa o leitor de tela que o relatório mudou (o aviso some e volta, para ser lido de novo).
document.addEventListener('htmx:afterSettle', (e) => {
  const aviso = document.getElementById('relatorio-aviso')
  if (!aviso || e.detail.target?.id !== 'relatorio') return
  aviso.textContent = ''
  setTimeout(() => { aviso.textContent = aviso.dataset.texto }, 100)
})

// --- presença (tickets/_presence.html) ------------------------------------------------------

// Com a aba escondida, o trecho não é pedido: "está vendo" é quem tem o chamado à vista. Sem
// isso, o Chrome espaça as consultas das abas de fundo para uma por minuto, mais que a validade
// da presença (45 s), e a pessoa aparecia e sumia.
document.addEventListener('htmx:beforeRequest', (e) => {
  if (document.hidden && e.detail.elt.id === 'presenca') e.preventDefault()
})

// --- cliente --------------------------------------------------------------------------------

function fecharOpcoes(caixa, restaurar = true) {
  const lista = caixa.querySelector('[data-opcoes]')
  lista.hidden = true
  caixa.querySelector('[role=combobox]').setAttribute('aria-expanded', 'false')
  // Texto digitado sem escolher: volta ao cliente escolhido (nas etiquetas, a busca fica vazia).
  const nome = caixa.querySelector('[name=cliente_nome]')
  if (restaurar) caixa.querySelector('[role=combobox]').value = nome ? nome.value : ''
}

function escolherCliente(caixa, opcao) {
  // Nas etiquetas (filtro dos relatórios), o cliente vira uma etiqueta e o filtro aplica.
  const etiquetas = caixa.closest('[data-chips]')
  if (etiquetas) {
    adicionarEtiqueta(etiquetas, opcao.dataset.id, opcao.dataset.nome)
    fecharOpcoes(caixa)
    aplicarFiltro(etiquetas)
    return
  }
  caixa.querySelector('[name=client_id]').value = opcao.dataset.id
  caixa.querySelector('[name=cliente_nome]').value = opcao.dataset.nome
  caixa.querySelector('[role=combobox]').value = opcao.dataset.nome
  fecharOpcoes(caixa, false)
  if ('enviaAoEscolher' in caixa.dataset) caixa.closest('form').requestSubmit()
}

document.addEventListener('htmx:afterSwap', (e) => {
  const lista = e.detail.target
  if (!lista.matches?.('[data-opcoes]')) return
  lista.hidden = false
  lista.closest('[data-cliente]').querySelector('[role=combobox]').setAttribute('aria-expanded', 'true')
})
document.addEventListener('mousedown', (e) => {
  const opcao = e.target.closest('[data-opcoes] [data-id]')
  if (!opcao) return
  e.preventDefault()
  escolherCliente(opcao.closest('[data-cliente]'), opcao)
})
document.addEventListener('keydown', (e) => {
  const campo = e.target.closest?.('[data-cliente] [role=combobox]')
  if (!campo) return
  const caixa = campo.closest('[data-cliente]')
  const lista = caixa.querySelector('[data-opcoes]')
  const opcoes = [...lista.querySelectorAll('[data-id]')]
  const atual = opcoes.findIndex((o) => o.getAttribute('aria-selected') === 'true')
  if (e.key === 'Escape') {
    fecharOpcoes(caixa)
  } else if (e.key === 'ArrowDown' && lista.hidden && caixa.closest('[data-chips]')) {
    // Nas etiquetas, a lista não abre ao receber o foco (o foco volta a ela depois de cada
    // filtro aplicado): abre com a seta.
    e.preventDefault()
    htmx.trigger(campo, 'abrir')
  } else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && opcoes.length && !lista.hidden) {
    e.preventDefault()
    const proxima = (atual + (e.key === 'ArrowDown' ? 1 : opcoes.length - 1)) % opcoes.length
    opcoes.forEach((o, i) => o.setAttribute('aria-selected', String(i === proxima)))
    campo.setAttribute('aria-activedescendant', opcoes[proxima].id)
    opcoes[proxima].scrollIntoView({ block: 'nearest' })
  } else if (e.key === 'Enter') {
    // Enter escolhe a opção marcada; nunca envia o formulário (como na SPA).
    e.preventDefault()
    if (atual >= 0 && !lista.hidden) escolherCliente(caixa, opcoes[atual])
  }
})
// Ao receber o foco, a lista abre com todos os clientes (não só o já escolhido) e o texto fica
// selecionado: digitar já começa uma busca nova.
document.addEventListener('focusin', (e) => {
  const campo = e.target.closest?.('[data-cliente] [role=combobox]')
  if (!campo || campo.closest('[data-chips]')) return
  campo.select()
  htmx.ajax('GET', '/clientes/opcoes', { target: campo.closest('[data-cliente]').querySelector('[data-opcoes]') })
})
document.addEventListener('focusout', (e) => {
  const caixa = e.target.closest?.('[data-cliente]')
  if (caixa && !caixa.contains(e.relatedTarget)) fecharOpcoes(caixa)
})
