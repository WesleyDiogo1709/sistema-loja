import { api, qs } from '../api.js';
import { h, clear, money, dateInput, field, select, table, errorToast, todayISO, monthStartISO, fmtDate, fmtDateTime, toast } from '../ui.js';
import { can, methodLabel } from '../state.js';

const FILTERS = {
  vendas: ['period', 'user', 'method', 'category', 'supplier'], lucro_produto: ['period', 'category', 'supplier', 'user'], lucro_venda: ['period', 'user', 'method'], mais_vendidos: ['period', 'category', 'supplier'],
  parados: ['category', 'supplier', 'days'], estoque: ['category', 'supplier', 'low'], forma_pagamento: ['period'], vendedor: ['period'], perdas: ['period'], movimentacoes: ['period'], contas_pagar: ['period'], os: ['period', 'user'],
  garantias: ['period'], caixas: ['period'], devolucoes: ['period'], aparelhos: [],
};
const fmt = (v, t) => { if (v === null || v === undefined || v === '') return ''; if (t === 'money') return money(v); if (t === 'date') return fmtDate(v); if (t === 'datetime') return fmtDateTime(v); if (t === 'percent') return String(v).replace('.', ',') + '%'; return String(v); };

export default async function ({ el }) {
  const list = await api.get('/api/reports');
  const [cats, users, sups, me] = await Promise.all([api.get('/api/categories').catch(() => []), api.get('/api/users/basic').catch(() => []), api.get('/api/suppliers').catch(() => []), api.get('/api/me')]);
  const name = select(list.map((r) => [r.key, r.label]), list[0]?.key);
  const from = dateInput(monthStartISO()), to = dateInput(todayISO());
  const cat = select([['', 'Todas'], ...cats.map((c) => [c, c])], ''), usr = select([['', 'Todos'], ...users.map((u) => [u.id, u.name])], ''), sup = select([['', 'Todos'], ...sups.map((s) => [s.name, s.name])], '');
  const meth = select([['', 'Todas'], ...me.payment_methods.map((m) => [m.key, m.label])], ''), days = h('input', { type: 'number', min: 1, value: 60 }), low = h('input', { type: 'checkbox' });
  const out = h('div'); const wrap = {};
  const mk = (k, label, input) => (wrap[k] = field(label, input));
  const filtersRow = h('div', { class: 'toolbar' }, field('Relatório', name), mk('periodFrom', 'De', from), mk('periodTo', 'Até', to), mk('user', 'Vendedor / técnico', usr), mk('method', 'Forma de pagamento', meth), mk('category', 'Categoria', cat), mk('supplier', 'Fornecedor', sup), mk('days', 'Dias sem vender', days),
    wrap.low = h('label', { class: 'check' }, low, 'Só abaixo do mínimo'));
  const run = h('button', { class: 'btn primary', onclick: () => load().catch(errorToast) }, 'Gerar relatório');
  const exports = h('div', { class: 'row noprint' });
  function params(extra = {}) { const f = FILTERS[name.value]; const p = {};
    if (f.includes('period')) { p.from = from.iso(); p.to = to.iso(); } if (f.includes('user') && usr.value) p.user_id = usr.value; if (f.includes('method') && meth.value) p.method = meth.value; if (f.includes('category') && cat.value) p.category = cat.value;
    if (f.includes('supplier') && sup.value) p.supplier = sup.value; if (f.includes('days')) p.days = days.value; if (f.includes('low') && low.checked) p.low = 1; return { ...p, ...extra }; }
  function syncFilters() { const f = FILTERS[name.value]; wrap.periodFrom.style.display = wrap.periodTo.style.display = f.includes('period') ? '' : 'none'; wrap.user.style.display = f.includes('user') ? '' : 'none'; wrap.method.style.display = f.includes('method') ? '' : 'none';
    wrap.category.style.display = f.includes('category') ? '' : 'none'; wrap.supplier.style.display = f.includes('supplier') ? '' : 'none'; wrap.days.style.display = f.includes('days') ? '' : 'none'; wrap.low.style.display = f.includes('low') ? '' : 'none'; }
  async function load() {
    const p = params(); if ((p.from === null) || (p.to === null)) { toast('Informe datas válidas (DD/MM/AAAA).', 'bad'); return; }
    const rep = await api.get(`/api/reports/${name.value}` + qs(p)); clear(out); clear(exports);
    const cols = rep.columns.map((c) => ({ label: c.label, num: ['money', 'int', 'percent'].includes(c.type), render: (r) => { const v = r[c.key]; if (c.key === 'method' || c.key === 'methods') return String(v || '').split(', ').map(methodLabel).join(', '); return fmt(v, c.type); } }));
    const footer = {}; rep.columns.forEach((c, i) => { if (rep.totals[c.key] !== undefined) footer[i] = null; });
    const tf = {}; rep.columns.forEach((c) => { if (rep.totals[c.key] !== undefined) tf[c.key] = fmt(rep.totals[c.key], c.type); });
    const colsKeyed = cols.map((c, i) => ({ ...c, key: rep.columns[i].key }));
    out.append(h('h3', { style: { margin: '8px 0' } }, rep.title), h('p', { class: 'muted' }, `${rep.rows.length} linha(s) · gerado em ${fmtDateTime(rep.generated_at)}`), table(colsKeyed, rep.rows, { footer: rep.rows.length && Object.keys(tf).length ? tf : null, empty: 'Nenhum dado para os filtros escolhidos.' }));
    exports.append(h('a', { class: 'btn', href: `/api/reports/${name.value}` + qs({ ...p, format: 'xlsx' }) }, 'Exportar Excel (.xlsx)'), h('a', { class: 'btn', href: `/api/reports/${name.value}` + qs({ ...p, format: 'csv' }) }, 'Exportar CSV'), h('button', { class: 'btn', onclick: () => window.print() }, 'Imprimir / salvar em PDF'));
  }
  name.addEventListener('change', () => { syncFilters(); clear(out); clear(exports); });
  el.append(filtersRow, h('div', { class: 'row noprint', style: { marginBottom: '12px' } }, run, exports), out); syncFilters(); await load();
}
