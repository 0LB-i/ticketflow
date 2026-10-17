// Aplica o tema antes da primeira pintura, para não piscar (docs/17 §17.4). Fica em arquivo
// próprio para a Content-Security-Policy não precisar liberar scripts embutidos. A chave é a
// mesma da SPA: a escolha vale nas duas interfaces enquanto convivem (ADR 0011).
try {
  var t = localStorage.getItem('tf-tema') || 'automatico'
  var dark =
    t === 'escuro' || (t === 'automatico' && matchMedia('(prefers-color-scheme: dark)').matches)
  if (dark) document.documentElement.classList.add('dark')
} catch (e) {}
