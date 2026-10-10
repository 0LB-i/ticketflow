// Aplica o tema e as cores personalizadas antes da primeira pintura, para não piscar
// (docs/17 §17.4). Fica em arquivo próprio para a Content-Security-Policy não precisar
// liberar scripts embutidos.
try {
  var t = localStorage.getItem('tf-tema') || 'automatico'
  var dark =
    t === 'escuro' || (t === 'automatico' && matchMedia('(prefers-color-scheme: dark)').matches)
  if (dark) document.documentElement.classList.add('dark')
  var idioma = localStorage.getItem('tf-idioma')
  if (idioma) document.documentElement.lang = idioma
  var cores = localStorage.getItem('tf-cores')
  if (cores) {
    var estilo = document.createElement('style')
    estilo.id = 'tf-cores'
    estilo.textContent = cores
    document.head.appendChild(estilo)
  }
} catch (e) {}
