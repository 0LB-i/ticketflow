/**
 * CPF, CNPJ (inclusive o alfanumérico, em vigor desde julho de 2026), telefone e CEP: formatação
 * para exibir e validação dos dígitos verificadores. A API guarda só os dígitos e valida de novo.
 */

/** Só números e letras maiúsculas (o CNPJ alfanumérico tem letras). */
export const normalizarDocumento = (valor: string) => valor.toUpperCase().replace(/[^0-9A-Z]/g, '')
export const soDigitos = (valor: string) => valor.replace(/\D/g, '')

function digito(caracteres: string, pesos: number[]) {
  const soma = [...caracteres].reduce((s, c, i) => s + (c.charCodeAt(0) - 48) * pesos[i]!, 0)
  const resto = soma % 11
  return resto < 2 ? 0 : 11 - resto
}

export function cpfValido(valor: string) {
  const cpf = soDigitos(valor)
  if (!/^\d{11}$/.test(cpf) || new Set(cpf).size === 1) return false
  const d1 = digito(cpf.slice(0, 9), [10, 9, 8, 7, 6, 5, 4, 3, 2])
  const d2 = digito(cpf.slice(0, 10), [11, 10, 9, 8, 7, 6, 5, 4, 3, 2])
  return cpf.slice(9) === `${d1}${d2}`
}

export function cnpjValido(valor: string) {
  const cnpj = normalizarDocumento(valor)
  if (!/^[0-9A-Z]{12}\d{2}$/.test(cnpj) || new Set(cnpj).size === 1) return false
  const pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
  const d1 = digito(cnpj.slice(0, 12), pesos.slice(1))
  const d2 = digito(cnpj.slice(0, 13), pesos)
  return cnpj.slice(12) === `${d1}${d2}`
}

/** Aplica a máscara enquanto se digita: "000.000.000-00" ou "00.000.000/0000-00". */
export function formatarDocumento(valor: string, tipo: 'person' | 'company') {
  if (tipo === 'person') {
    const d = soDigitos(valor).slice(0, 11)
    return d
      .replace(/^(\d{3})(\d)/, '$1.$2')
      .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
      .replace(/\.(\d{3})(\d)/, '.$1-$2')
  }
  const c = normalizarDocumento(valor).slice(0, 14)
  return c
    .replace(/^(\w{2})(\w)/, '$1.$2')
    .replace(/^(\w{2})\.(\w{3})(\w)/, '$1.$2.$3')
    .replace(/^(\w{2})\.(\w{3})\.(\w{3})(\w)/, '$1.$2.$3/$4')
    .replace(/\/(\w{4})(\w)/, '/$1-$2')
}

/** "(11) 3333-4444" ou "(11) 98765-4321". */
export function formatarTelefone(valor: string) {
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

export const telefoneValido = (valor: string) => /^[1-9]{2}\d{8,9}$/.test(soDigitos(valor))

/** "01310-100". */
export function formatarCep(valor: string) {
  const d = soDigitos(valor).slice(0, 8)
  return d.length > 5 ? `${d.slice(0, 5)}-${d.slice(5)}` : d
}

// prettier-ignore
export const UFS = [
  'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA',
  'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO',
] as const
