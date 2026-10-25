(function () {
  var p = document.getElementById('btn-print'), c = document.getElementById('btn-close');
  if (p) p.addEventListener('click', function () { window.print(); });
  if (c) c.addEventListener('click', function () { window.close(); });

  // Bobina térmica: o Chromium não aceita "size: 80mm auto". Ajustamos a altura da página ao tamanho real do cupom,
  // para sair uma única tira contínua (sem cortar em A4/Carta). Sem JS, vale o tamanho fixo do @page do modelo.
  function fitThermalPage() {
    var t = document.querySelector('.ticket[data-paper]');
    if (!t) return;
    var paper = parseInt(t.getAttribute('data-paper'), 10) || 80;
    var mm = Math.ceil(t.getBoundingClientRect().height * 25.4 / 96) + 6;
    mm = Math.max(60, Math.min(mm, 2000));
    var s = document.getElementById('page-size');
    if (!s) { s = document.createElement('style'); s.id = 'page-size'; document.head.appendChild(s); }
    s.textContent = '@page { size: ' + paper + 'mm ' + mm + 'mm; margin: 0; }';
  }
  fitThermalPage();
  window.addEventListener('load', fitThermalPage);
  window.addEventListener('beforeprint', fitThermalPage);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitThermalPage);

  if (location.search.indexOf('print=1') >= 0) setTimeout(function () { fitThermalPage(); window.print(); }, 300);
})();
