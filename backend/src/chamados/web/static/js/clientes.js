// Formulário de cliente (templates/clients/form.html): campos de pessoa física ou jurídica
// conforme o tipo, máscaras e as listas de telefones e e-mails. JavaScript puro (ADR 0011).

const tipo = (form) => form.querySelector('input[name=kind]:checked')?.value ?? 'person'

/** Mostra só os campos do tipo escolhido; os do outro tipo a API ignora. */
function mostrarTipo(form) {
  const atual = tipo(form)
  for (const el of form.querySelectorAll('[data-se-tipo]')) el.hidden = el.dataset.seTipo !== atual
}

const soDigitos = (v) => v.replace(/\D/g, '')

/** "000.000.000-00" ou "00.000.000/0000-00" (o CNPJ alfanumérico tem letras). */
function formatarDocumento(valor, t) {
  if (t === 'person') {
    return soDigitos(valor)
      .slice(0, 11)
      .replace(/^(\d{3})(\d)/, '$1.$2')
      .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
      .replace(/\.(\d{3})(\d)/, '.$1-$2')
  }
  return valor
    .toUpperCase()
    .replace(/[^0-9A-Z]/g, '')
    .slice(0, 14)
    .replace(/^(\w{2})(\w)/, '$1.$2')
    .replace(/^(\w{2})\.(\w{3})(\w)/, '$1.$2.$3')
    .replace(/^(\w{2})\.(\w{3})\.(\w{3})(\w)/, '$1.$2.$3/$4')
    .replace(/\/(\w{4})(\w)/, '/$1-$2')
}

/** "(11) 3333-4444" ou "(11) 98765-4321". */
function formatarTelefone(valor) {
  let d = soDigitos(valor)
  if ((d.length === 12 || d.length === 13) && d.startsWith('55')) d = d.slice(2)
  d = d.slice(0, 11)
  if (d.length <= 2) return d
  const meio = d.length === 11 ? 5 : 4
  const numero = d.slice(2)
  return numero.length > meio
    ? `(${d.slice(0, 2)}) ${numero.slice(0, meio)}-${numero.slice(meio)}`
    : `(${d.slice(0, 2)}) ${numero}`
}

function formatarCep(valor) {
  const d = soDigitos(valor).slice(0, 8)
  return d.length > 5 ? `${d.slice(0, 5)}-${d.slice(5)}` : d
}

const MASCARAS = {
  documento: (v, form) => formatarDocumento(v, tipo(form)),
  telefone: formatarTelefone,
  cep: formatarCep,
  rg: (v) => soDigitos(v).slice(0, 14),
}

document.addEventListener('input', (e) => {
  const mascara = MASCARAS[e.target.dataset?.mascara]
  if (mascara) e.target.value = mascara(e.target.value, e.target.form)
})
document.addEventListener('change', (e) => {
  if (e.target.name !== 'kind') return
  const form = e.target.form
  mostrarTipo(form)
  const documento = form.querySelector('[data-mascara=documento]')
  documento.value = formatarDocumento(documento.value, tipo(form))
})

/** "Telefone 1", "Telefone 2"… só quando há mais de uma linha. */
function numerar(lista) {
  const linhas = lista.querySelectorAll('[data-linha]')
  linhas.forEach((linha, i) => {
    const rotulo = linha.querySelector('[data-rotulo]')
    rotulo.textContent = linhas.length > 1 ? `${rotulo.dataset.rotulo} ${i + 1}` : rotulo.dataset.rotulo
  })
}

document.addEventListener('click', (e) => {
  const adicionar = e.target.closest('[data-adiciona-linha]')
  if (adicionar) {
    const lista = adicionar.closest('[data-repetivel]')
    const linha = lista.querySelector('template').content.firstElementChild.cloneNode(true)
    lista.querySelector('[data-linhas]').append(linha)
    numerar(lista)
    linha.querySelector('input').focus()
  }
  const remover = e.target.closest('[data-remove-linha]')
  if (remover) {
    const lista = remover.closest('[data-repetivel]')
    remover.closest('[data-linha]').remove()
    numerar(lista)
  }
})
