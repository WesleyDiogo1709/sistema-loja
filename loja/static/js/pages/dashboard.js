import { api } from '../api.js';
import { h, money, table, badge, fmtDateTime, fmtDate } from '../ui.js';
import { state, can } from '../state.js';

const stat = (label, value, sub, alert) => h('div', { class: 'card stat' + (alert ? ' alert' : '') }, h('div', { class: 'l' }, label), h('div', { class: 'v' }, value), sub ? h('div', { class: 's' }, sub) : null);

export default async function ({ el }) {
  const d = await api.get('/api/dashboard');
  const cards = h('div', { class: 'cards' },
    stat('Vendas de hoje', money(d.sales_today.total_cents), `${d.sales_today.count} venda(s)`),
    d.revenue_month ? stat('Faturamento do mês', money(d.revenue_month.total_cents), `${d.revenue_month.count} venda(s) concluída(s)`) : null,
    d.gross_profit_month_cents !== undefined ? stat('Lucro bruto estimado no mês', money(d.gross_profit_month_cents), 'vendas − custo real − devoluções') : null,
    stat('Produtos em estoque', String(d.stock_units), `${d.products_active} produtos ativos · ${d.devices_in_stock} aparelhos`),
    stat('Abaixo do estoque mínimo', String(d.low_stock.length), 'precisam de reposição', d.low_stock.length > 0),
    stat('Ordens de serviço em andamento', String(d.os_open), d.os_late ? `${d.os_late} com prazo vencido` : 'nenhuma atrasada', d.os_late > 0),
    stat('Aparelhos prontos p/ retirada', String(d.os_ready.length), 'aguardando o cliente'));
  const cash = d.cash.open
    ? h('div', { class: 'card' }, h('h3', {}, 'Caixa'), h('div', {}, badge('Aberto', 'good'), ' desde ', fmtDateTime(d.cash.opened_at)),
      d.cash.expected_cash_cents !== undefined ? h('dl', { class: 'kv', style: { marginTop: '10px' } },
        h('dt', {}, 'Troco inicial'), h('dd', {}, money(d.cash.opening_cents)), h('dt', {}, 'Vendas'), h('dd', {}, `${d.cash.sales_count} · ${money(d.cash.sales_total_cents)}`),
        h('dt', {}, 'Dinheiro esperado'), h('dd', {}, h('b', {}, money(d.cash.expected_cash_cents)))) : null)
    : h('div', { class: 'card' }, h('h3', {}, 'Caixa'), badge('Fechado', 'warn'));
  const topMax = Math.max(1, ...d.top_sold.map((t) => t.qty));
  const top = h('div', { class: 'card' }, h('h3', {}, 'Mais vendidos (30 dias)'),
    d.top_sold.length ? d.top_sold.map((t) => h('div', { style: { margin: '8px 0' } }, h('div', { class: 'row between' }, h('span', {}, t.name), h('b', {}, t.qty + ' un.')),
      h('div', { style: { background: 'var(--accent-l)', height: '6px', borderRadius: '3px' } }, h('div', { style: { width: (t.qty / topMax * 100) + '%', background: 'var(--accent)', height: '6px', borderRadius: '3px' } })))) : h('div', { class: 'muted' }, 'Ainda não há vendas no período.'));
  const low = h('div', { class: 'card' }, h('h3', {}, 'Estoque baixo'), table([{ label: 'Produto', key: 'name' }, { label: 'Estoque', key: 'qty', num: true }, { label: 'Mínimo', key: 'min_qty', num: true }], d.low_stock.slice(0, 8), { empty: 'Nenhum produto abaixo do mínimo.' }));
  const ready = h('div', { class: 'card' }, h('h3', {}, 'Prontos para retirada'), table([{ label: 'OS', render: (r) => '#' + r.id }, { label: 'Cliente', key: 'customer_name' }, { label: 'Aparelho', render: (r) => `${r.brand} ${r.model}` }, { label: 'Pronto em', render: (r) => fmtDate(r.completed_at) }], d.os_ready, { empty: 'Nenhum aparelho aguardando retirada.', onRow: () => { location.hash = '#/os'; } }));
  const stalled = h('div', { class: 'card' }, h('h3', {}, 'Produtos parados'), table([{ label: 'Produto', key: 'name' }, { label: 'Estoque', key: 'qty', num: true }], d.stalled.slice(0, 8), { empty: 'Nenhum produto parado.' }));
  const margin = d.top_margin ? h('div', { class: 'card' }, h('h3', {}, 'Maior margem (cadastro)'), table([{ label: 'Produto', key: 'name' }, { label: 'Margem', render: (r) => r.margin.toLocaleString('pt-BR') + '%', num: true }], d.top_margin)) : null;
  const pay = d.payables_soon ? h('div', { class: 'card' }, h('h3', {}, 'Contas a pagar nos próximos 7 dias'), table([{ label: 'Vencimento', render: (r) => fmtDate(r.due_date) }, { label: 'Descrição', key: 'description' }, { label: 'Valor', render: (r) => money(r.amount_cents), num: true }], d.payables_soon, { empty: 'Nenhuma conta a vencer.' })) : null;
  el.append(cards, h('div', { class: 'grid2' }, cash, top, low, ready, stalled, margin, pay));
}
