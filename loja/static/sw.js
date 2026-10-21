/* Service worker do Sistema da Loja.
   Regra de segurança: NUNCA guarda dados (API, impressões, relatórios) nem exibe informação antiga como se fosse atual.
   Ele existe para o app ser instalável e para mostrar um aviso claro quando não há conexão. */
const VERSION = 'loja-sw-1';
const OFFLINE_HTML = `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sem conexão</title>
<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#14201c;color:#fff;display:grid;place-items:center;min-height:100vh;margin:0;padding:24px;text-align:center}
main{max-width:420px}h1{font-size:22px}p{color:#cfdad4;line-height:1.5}button{font:inherit;padding:12px 20px;border-radius:6px;border:0;background:#f2b705;color:#2b2100;font-weight:700;margin-top:12px}</style></head>
<body><main><h1>Sem conexão com a internet</h1><p>O sistema precisa de internet para mostrar dados atuais e registrar vendas e estoque. Nada foi salvo neste aparelho. Confira sua conexão e tente de novo.</p>
<button onclick="location.reload()">Tentar novamente</button></main></body></html>`;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil((async () => {
  for (const k of await caches.keys()) await caches.delete(k); // não mantém cache nenhum
  await self.clients.claim();
})()));

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  if (req.mode === 'navigate') {
    // Sempre vai à rede. Sem rede: aviso de indisponibilidade, nunca página antiga.
    event.respondWith(fetch(req, { cache: 'no-store' }).catch(() => new Response(OFFLINE_HTML, { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } })));
  }
  // Demais pedidos (API, scripts, estilos): passam direto para a rede, sem cache.
});
