import { api, setUnauthenticatedHandler, setOnline } from './api.js';
import { h, clear, toast, errorToast, modal, field, askText } from './ui.js';
import { state, can, canAny } from './state.js';

// [rota, título, módulo, permissões aceitas (qualquer uma) ou null]
const ROUTES = [
  ['inicio', 'Início', () => import('./pages/dashboard.js'), null, 'Geral'],
  ['pdv', 'Ponto de venda', () => import('./pages/pdv.js'), ['vender'], 'Vendas'],
  ['vendas', 'Histórico de vendas', () => import('./pages/sales.js'), ['vender', 'ver_financeiro'], 'Vendas'],
  ['caixa', 'Caixa', () => import('./pages/cash.js'), ['gerenciar_caixa', 'ver_financeiro'], 'Vendas'],
  ['produtos', 'Produtos e estoque', () => import('./pages/products.js'), ['gerenciar_produtos', 'movimentar_estoque', 'ajustar_estoque', 'vender'], 'Estoque'],
  ['inventario', 'Inventário', () => import('./pages/inventory.js'), ['ajustar_estoque'], 'Estoque'],
  ['aparelhos', 'Aparelhos (IMEI)', () => import('./pages/devices.js'), ['gerenciar_aparelhos', 'vender'], 'Estoque'],
  ['os', 'Assistência técnica', () => import('./pages/service.js'), ['gerenciar_os'], 'Assistência'],
  ['clientes', 'Clientes', () => import('./pages/people.js'), ['ver_clientes'], 'Cadastros'],
  ['fornecedores', 'Fornecedores', () => import('./pages/people.js'), ['gerenciar_produtos', 'gerenciar_financeiro'], 'Cadastros'],
  ['posvenda', 'Garantias e devoluções', () => import('./pages/aftersales.js'), ['gerenciar_garantias', 'registrar_devolucoes', 'vender'], 'Pós-venda'],
  ['financeiro', 'Financeiro', () => import('./pages/finance.js'), ['ver_financeiro'], 'Gestão'],
  ['relatorios', 'Relatórios', () => import('./pages/reports.js'), ['ver_relatorios'], 'Gestão'],
  ['leitor', 'Teste do leitor', () => import('./pages/scanner.js'), ['vender', 'gerenciar_produtos', 'movimentar_estoque'], 'Sistema'],
  ['config', 'Configurações', () => import('./pages/settings.js'), ['gerenciar_config', 'gerenciar_usuarios', 'gerenciar_backup', 'ver_auditoria'], 'Sistema'],
];
const allowed = (r) => !r[3] || canAny(...r[3]);
let cleanup = null;
let renderToken = 0;

const $ = (id) => document.getElementById(id);

async function boot() {
  setUnauthenticatedHandler(showLogin);
  try { applyMe(await api.get('/api/me')); route(); }
  catch (e) { showLogin(); }
}

function showLogin() {
  $('app').classList.add('hidden'); $('login').classList.remove('hidden');
  $('login-pass').value = ''; $('login-user').focus();
}

function applyMe(me) {
  state.me = me.user; state.perms = new Set(me.permissions); state.settings = me.settings; state.methods = me.payment_methods;
  state.cashOpen = me.cash_open;
  $('login').classList.add('hidden'); $('app').classList.remove('hidden');
  $('brand').textContent = me.settings.store_name || 'Loja';
  document.title = (me.settings.store_name || 'Loja') + ' — Sistema de gestão';
  $('who').replaceChildren(me.user.name, h('small', {}, me.user.role));
  buildNav(); updateCashBadge();
  if (me.user.must_change_password) forcePasswordChange();
}

function buildNav() {
  const nav = clear($('nav'));
  let group = null;
  ROUTES.filter(allowed).forEach((r) => {
    if (r[4] !== group) { group = r[4]; nav.append(h('div', { class: 'group' }, group)); }
    nav.append(h('a', { href: '#/' + r[0], 'data-route': r[0] }, r[1]));
  });
}

export function updateCashBadge() {
  const b = $('cash-badge');
  b.className = 'badge ' + (state.cashOpen ? 'good' : 'warn');
  b.textContent = state.cashOpen ? 'Caixa aberto' : 'Caixa fechado';
}
export async function refreshMe() { const me = await api.get('/api/me'); state.cashOpen = me.cash_open; state.methods = me.payment_methods; state.settings = me.settings; updateCashBadge(); }

async function route() {
  if (!state.me || state.me.must_change_password) return; // enquanto a senha provisória não é trocada, nenhuma tela carrega
  const name = (location.hash.replace(/^#\//, '').split('?')[0]) || 'inicio';
  let r = ROUTES.find((x) => x[0] === name && allowed(x)) || ROUTES[0];
  if (cleanup) { try { cleanup(); } catch (e) { /* ignora */ } cleanup = null; }
  document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.route === r[0]));
  $('page-title').textContent = r[1];
  const page = clear($('page'));
  const token = ++renderToken;
  try {
    const mod = await r[2]();
    if (token !== renderToken) return;
    const result = await mod.default({ el: page, route: r[0], setTitle: (t) => { $('page-title').textContent = t; } });
    if (token === renderToken && typeof result === 'function') cleanup = result;
  } catch (e) {
    if (token === renderToken) page.append(h('div', { class: 'alertbox bad' }, 'Não foi possível abrir esta tela: ' + e.message));
    console.error(e);
  }
}

async function forcePasswordChange() {
  while (state.me && state.me.must_change_password) {
    const cur = h('input', { type: 'password' }), nw = h('input', { type: 'password' }), nw2 = h('input', { type: 'password' });
    const ok = await modal({ title: 'Defina uma nova senha', noCancel: true,
      content: [h('p', { style: { margin: 0 } }, 'Por segurança, troque a senha provisória antes de continuar. Escolha uma senha longa e difícil de adivinhar (o sistema avisa o tamanho mínimo).'),
        field('Senha atual', cur), field('Nova senha', nw), field('Repita a nova senha', nw2)],
      buttons: [{ label: 'Salvar nova senha', kind: 'primary', onClick: async (close) => {
        if (nw.value !== nw2.value) { toast('As senhas digitadas não são iguais.', 'bad'); return; }
        await api.post('/api/me/password', { current: cur.value, new: nw.value });
        close(true);
      } }] });
    if (ok) { state.me.must_change_password = false; toast('Senha alterada.', 'good'); route(); }
  }
}

$('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = $('login-error'); err.classList.add('hidden');
  try {
    applyMe(await api.post('/api/login', { username: $('login-user').value, password: $('login-pass').value }));
    location.hash = '#/inicio'; route();
  } catch (ex) { err.textContent = ex.message; err.classList.remove('hidden'); $('login-pass').select(); }
});
$('btn-logout').addEventListener('click', async () => {
  try { await api.post('/api/logout'); } catch (e) { /* ignora */ }
  state.me = null; if (cleanup) cleanup(); location.hash = ''; showLogin();
});
$('btn-pass').addEventListener('click', async () => {
  const cur = h('input', { type: 'password' }), nw = h('input', { type: 'password' });
  await modal({ title: 'Trocar senha', size: 'narrow', content: [field('Senha atual', cur), field('Nova senha', nw)],
    buttons: [{ label: 'Salvar', kind: 'primary', onClick: async (close) => { await api.post('/api/me/password', { current: cur.value, new: nw.value }); toast('Senha alterada.', 'good'); close(true); } }] });
});
window.addEventListener('hashchange', route);

// Indicador de conexão: consulta /api/health a cada 15 s e reage às falhas das chamadas normais.
function showConn(online) {
  const b = $('conn-badge'); b.className = 'badge ' + (online ? 'good' : 'bad'); b.textContent = online ? 'Online' : 'Sem conexão';
  $('conn-banner').classList.toggle('hidden', online);
}
window.addEventListener('loja:conexao', (e) => showConn(e.detail));
window.addEventListener('offline', () => setOnline(false));
async function pingServidor() {
  try { const r = await fetch('/api/health', { cache: 'no-store' }); setOnline(r.ok); }
  catch (e) { setOnline(false); }
}
setInterval(pingServidor, 15000);
window.addEventListener('online', pingServidor);

// Menu em gaveta (celular)
function menu(open) { $('sidebar').classList.toggle('open', open); $('scrim').classList.toggle('hidden', !open); $('btn-menu').setAttribute('aria-expanded', String(open)); }
$('btn-menu').addEventListener('click', () => menu(!$('sidebar').classList.contains('open')));
$('scrim').addEventListener('click', () => menu(false));
$('nav').addEventListener('click', (e) => { if (e.target.closest('a')) menu(false); });

if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js').catch(() => {}); }

// Atalhos globais
document.addEventListener('keydown', (e) => {
  if (!state.me || document.querySelector('.overlay')) return;
  const go = (r) => { if (ROUTES.some((x) => x[0] === r && allowed(x))) { e.preventDefault(); location.hash = '#/' + r; } };
  if (e.key === 'F2') go('pdv');
  else if (e.key === 'F4') go('caixa');
  else if (e.key === 'F3') {
    if (!canAny('vender', 'gerenciar_produtos', 'movimentar_estoque')) return;
    e.preventDefault(); quickSearch();
  }
});

async function quickSearch() {
  const input = h('input', { placeholder: 'Nome, código de barras, SKU...', autocomplete: 'off' });
  const out = h('div', { class: 'results' });
  let t;
  input.addEventListener('input', () => { clearTimeout(t); t = setTimeout(async () => {
    const q = input.value.trim(); clear(out); if (q.length < 2) return;
    try {
      const rows = await api.get('/api/products?q=' + encodeURIComponent(q));
      rows.slice(0, 12).forEach((p) => out.append(h('button', { type: 'button' }, h('span', {}, p.name), h('span', {}, `${(p.price_cents / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })} · estoque ${p.qty}`))));
      if (!rows.length) out.append(h('div', { class: 'empty' }, 'Nenhum produto encontrado.'));
    } catch (ex) { errorToast(ex); }
  }, 200); });
  modal({ title: 'Consulta rápida de produto', content: [field('Buscar', input), out], noCancel: false, cancelLabel: 'Fechar' });
}

boot();
