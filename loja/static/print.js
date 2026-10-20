(function () {
  var p = document.getElementById('btn-print'), c = document.getElementById('btn-close');
  if (p) p.addEventListener('click', function () { window.print(); });
  if (c) c.addEventListener('click', function () { window.close(); });
  if (location.search.indexOf('print=1') >= 0) setTimeout(function () { window.print(); }, 300);
})();
