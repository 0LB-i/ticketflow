// Chat do WhatsApp (web/templates/whatsapp/index.html): Enter envia (Shift+Enter quebra a linha), o
// campo cresce com o texto, a conversa abre no fim e continua no fim quando chega mensagem (se a
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
  if (campo.value.trim()) campo.form.requestSubmit()
})

document.addEventListener('input', (e) => {
  if (e.target.matches?.('[data-envia-com-enter]')) ajustarAltura(e.target)
})

// Antes da troca: onde estava a rolagem. O erro do envio (422) também troca, para aparecer.
const rolagem = {}
document.addEventListener('htmx:beforeSwap', (e) => {
  const alvo = e.detail.target
  if (!alvo) return
  if (alvo.id === 'mensagens') {
    rolagem.noFim = alvo.scrollHeight - alvo.scrollTop - alvo.clientHeight < PERTO_DO_FIM
    rolagem.mensagens = alvo.scrollTop
    if (e.detail.xhr.status === 422) {
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
})

// Enviada: o campo fica limpo (no erro, o texto continua lá).
document.addEventListener('htmx:afterRequest', (e) => {
  const form = e.detail.elt
  if (form?.id !== 'escrever' || !e.detail.successful) return
  form.reset()
  const campo = form.querySelector('[data-envia-com-enter]')
  if (campo) {
    ajustarAltura(campo)
    campo.focus()
  }
})
