// Chat do WhatsApp (web/templates/whatsapp/index.html): Enter envia (Shift+Enter quebra a linha), o
// campo cresce com o texto, os arquivos escolhidos (pelo clipe ou arrastados sobre as mensagens)
// aparecem acima do campo (com o X para tirar), o
// envio mostra o progresso, a conversa abre no fim e continua no fim quando chega mensagem (se a
// pessoa estava lá embaixo), e a lista de conversas não volta ao topo ao se atualizar.

const PERTO_DO_FIM = 80 // px

function rolarAteOFim () {
  const mensagens = document.getElementById('mensagens')
  if (mensagens) mensagens.scrollTop = mensagens.scrollHeight
}

function ajustarAltura (campo) {
  campo.style.height = 'auto'
  campo.style.height = `${campo.scrollHeight}px`
}

function tamanho (bytes) {
  const unidades = ['B', 'KB', 'MB', 'GB']
  let valor = bytes
  let i = 0
  while (valor >= 1024 && i < unidades.length - 1) {
    valor /= 1024
    i++
  }
  return `${valor.toLocaleString(document.documentElement.lang, { maximumFractionDigits: i ? 1 : 0 })} ${unidades[i]}`
}

// Os arquivos escolhidos, como etiquetas com o X para tirar um deles.
function mostrarAnexos (entrada) {
  const lista = document.getElementById('anexos')
  if (!lista) return
  lista.replaceChildren()
  const arquivos = Array.from(entrada.files)
  arquivos.forEach((arquivo, indice) => {
    const item = document.createElement('li')
    item.className = 'inline-flex max-w-xs items-center gap-2 rounded-md bg-surface-raised px-2 py-1 text-sm'
    const nome = document.createElement('span')
    nome.className = 'truncate'
    nome.textContent = `${arquivo.name} · ${tamanho(arquivo.size)}`
    const tirar = document.createElement('button')
    tirar.type = 'button'
    tirar.className = 'shrink-0 rounded px-1 text-muted hover:text-fg'
    tirar.textContent = '×'
    tirar.setAttribute('aria-label', `${entrada.dataset.tirar || 'Remover'} ${arquivo.name}`)
    tirar.addEventListener('click', () => {
      const restantes = new DataTransfer()
      Array.from(entrada.files).forEach((f, i) => { if (i !== indice) restantes.items.add(f) })
      entrada.files = restantes.files
      mostrarAnexos(entrada)
    })
    item.append(nome, tirar)
    lista.append(item)
  })
  lista.hidden = arquivos.length === 0
}

document.addEventListener('DOMContentLoaded', () => {
  rolarAteOFim()
  const campo = document.querySelector('[data-envia-com-enter]')
  if (campo) {
    ajustarAltura(campo)
    campo.focus()
  }
})

document.addEventListener('keydown', (e) => {
  const campo = e.target.closest?.('[data-envia-com-enter]')
  if (!campo || e.key !== 'Enter' || e.shiftKey || e.isComposing) return
  e.preventDefault()
  const arquivos = campo.form.querySelector('[data-anexos-entrada]')
  if (campo.value.trim() || arquivos?.files.length) campo.form.requestSubmit()
})

document.addEventListener('input', (e) => {
  if (e.target.matches?.('[data-envia-com-enter]')) ajustarAltura(e.target)
})

document.addEventListener('change', (e) => {
  if (e.target.matches?.('[data-anexos-entrada]')) {
    mostrarAnexos(e.target)
    document.querySelector('[data-envia-com-enter]')?.focus()
  }
})

// Arrastar arquivos sobre as mensagens (#area-mensagens, entre o nome da conversa e o campo de
// escrever): o aviso aparece e, ao soltar, os arquivos se juntam aos já escolhidos. Só arrastando
// arquivos (não um texto). Fora dessa área, soltar não faz nada (o navegador não abre o arquivo).
function arrastandoArquivos (e) {
  return Array.from(e.dataTransfer?.types || []).includes('Files')
}

document.addEventListener('dragover', (e) => {
  if (!arrastandoArquivos(e) || !document.getElementById('area-mensagens')) return
  e.preventDefault() // sem isto, o navegador abre o arquivo no lugar da tela
  e.dataTransfer.dropEffect = e.target.closest?.('#area-mensagens') ? 'copy' : 'none'
})
document.addEventListener('drop', (e) => {
  if (arrastandoArquivos(e) && document.getElementById('area-mensagens')) e.preventDefault()
})

function prepararArrastar () {
  const area = document.getElementById('area-mensagens')
  const aviso = document.getElementById('soltar')
  const entrada = document.querySelector('[data-anexos-entrada]')
  if (!area || !aviso || !entrada) return
  let arrastos = 0 // dragenter e dragleave disparam a cada elemento por baixo do mouse
  area.addEventListener('dragenter', (e) => {
    if (!arrastandoArquivos(e)) return
    arrastos++
    aviso.hidden = false
  })
  area.addEventListener('dragleave', (e) => {
    if (!arrastandoArquivos(e)) return
    arrastos = Math.max(0, arrastos - 1)
    if (!arrastos) aviso.hidden = true
  })
  area.addEventListener('drop', (e) => {
    if (!arrastandoArquivos(e)) return
    e.preventDefault()
    arrastos = 0
    aviso.hidden = true
    const juntos = new DataTransfer()
    for (const arquivo of [...entrada.files, ...e.dataTransfer.files]) juntos.items.add(arquivo)
    entrada.files = juntos.files
    mostrarAnexos(entrada)
    document.querySelector('[data-envia-com-enter]')?.focus()
  })
}
document.addEventListener('DOMContentLoaded', prepararArrastar)

// Sem texto e sem arquivo, não envia.
document.addEventListener('submit', (e) => {
  const form = e.target
  if (form.id !== 'escrever') return
  const texto = form.querySelector('[data-envia-com-enter]')
  const arquivos = form.querySelector('[data-anexos-entrada]')
  if (!texto?.value.trim() && !arquivos?.files.length) e.preventDefault()
}, true)

// O progresso do envio dos arquivos.
document.addEventListener('htmx:xhr:progress', (e) => {
  const form = e.detail.elt
  if (form?.id !== 'escrever' || !e.detail.lengthComputable) return
  if (!form.querySelector('[data-anexos-entrada]')?.files.length) return
  const progresso = document.getElementById('progresso')
  progresso.hidden = false
  progresso.textContent = `${Math.round((e.detail.loaded / e.detail.total) * 100)}%`
})

// Antes da troca: onde estava a rolagem. O erro do envio (422, 507) também troca, para aparecer.
const rolagem = {}
document.addEventListener('htmx:beforeSwap', (e) => {
  const alvo = e.detail.target
  if (!alvo) return
  if (alvo.id === 'mensagens') {
    rolagem.noFim = alvo.scrollHeight - alvo.scrollTop - alvo.clientHeight < PERTO_DO_FIM
    rolagem.mensagens = alvo.scrollTop
    if ([422, 507].includes(e.detail.xhr.status)) {
      e.detail.shouldSwap = true
      e.detail.isError = false
    }
  }
  const lista = document.querySelector('[data-mantem-rolagem]')
  if (lista) rolagem.lista = lista.scrollTop
})

document.addEventListener('htmx:afterSwap', (e) => {
  const lista = document.querySelector('[data-mantem-rolagem]')
  if (lista && rolagem.lista !== undefined) lista.scrollTop = rolagem.lista
  if (e.detail.target?.id !== 'mensagens') return
  const mensagens = document.getElementById('mensagens')
  // Quem mandou a mensagem vai ao fim; quem lia mais acima continua onde estava.
  const enviou = e.detail.requestConfig?.elt?.id === 'escrever'
  if (enviou || rolagem.noFim) rolarAteOFim()
  else if (mensagens) mensagens.scrollTop = rolagem.mensagens
  // As fotos carregam depois: quem está no fim continua no fim.
  if (enviou || rolagem.noFim) {
    mensagens?.querySelectorAll('img, video').forEach((midia) => {
      midia.addEventListener('load', rolarAteOFim, { once: true })
      midia.addEventListener('loadedmetadata', rolarAteOFim, { once: true })
    })
  }
})

// Enviada: o campo e os arquivos ficam limpos (no erro, continuam lá).
document.addEventListener('htmx:afterRequest', (e) => {
  const form = e.detail.elt
  if (form?.id !== 'escrever') return
  const progresso = document.getElementById('progresso')
  if (progresso) progresso.hidden = true
  if (!e.detail.successful) return
  form.reset()
  const entrada = form.querySelector('[data-anexos-entrada]')
  if (entrada) mostrarAnexos(entrada)
  const campo = form.querySelector('[data-envia-com-enter]')
  if (campo) {
    ajustarAltura(campo)
    campo.focus()
  }
})

// Na abertura, as fotos também empurram a conversa: fica no fim depois que carregam.
window.addEventListener('load', rolarAteOFim)
