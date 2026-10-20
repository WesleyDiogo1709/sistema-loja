import { api, qs } from '../api.js';
import { h, clear, money, table, badge, fmtDateTime, field, dateInput, todayISO, select, modal, withAuth, askText, toast, errorToast, openPrint, confirmBox, moneyInput } from '../ui.js';
import { state, can, methodLabel } from '../state.js';

export default async function ({ el }) {
  const from = dateInput(todayISO(-6)), to = dateInput(todayISO()), q = h('input', { placeholder: 'Nº da venda, cliente ou vendedor' });
  const status = select([['', 'Todas'], ['concluida', 'Concluídas'], ['cancelada', 'Canceladas']], '');
  const out = h('div');
  async function load() {
    clear(out);
    const rows = await api.get('/api/sales' + qs({ from: from.iso(), to: to.iso(), q: q.value.trim(), status: status.value }));
    const ok = rows.filter((r) => r.status === 'concluida');
    out.append(h('p', { class: 'muted' }, `${rows.length} venda(s) · concluídas somam ${money(ok.reduce((a, r) => a + r.total_cents, 0))}`),
      table([{ label: 'Nº', render: (r) => '#' + r.id }, { label: 'Data', render: (r) => fmtDateTime(r.created_at) }, { label: 'Vendedor', key: 'seller' }, { label: 'Cliente', render: (r) => r.customer_name || '—' },
        { label: 'Pagamento', render: (r) => (r.methods || '').split(', ').map(methodLabel).join(', ') }, { label: 'Total', render: (r) => money(r.total_cents), num: true },
        { label: 'Situação', render: (r) => badge(r.status === 'concluida' ? 'Concluída' : 'Cancelada', r.status === 'concluida' ? 'good' : 'bad') }], rows, { onRow: (r) => detail(r.id), empty: 'Nenhuma venda encontrada neste período.' }));
  }
  async function detail(id) {
    const s = await api.get('/api/sales/' + id);
    const items = table([{ label: 'Item', key: 'product_name' }, { label: 'Qtd.', key: 'qty', num: true }, { label: 'Unit.', render: (i) => money(i.unit_price_cents), num: true },
      { label: 'Desc.', render: (i) => (i.discount_cents ? money(i.discount_cents) : ''), num: true }, { label: 'Total', render: (i) => money(i.total_cents), num: true },
      { label: 'Garantia até', render: (i) => (i.warranty_ends ? i.warranty_ends.split('-').reverse().join('/') : '') }, { label: 'Devolvidos', render: (i) => (i.returned_qty || ''), num: true }], s.items);
    const pays = table([{ label: 'Forma', render: (p) => methodLabel(p.method) + (p.installments > 1 ? ` ${p.installments}x` : '') }, { label: 'Valor', render: (p) => money(p.amount_cents), num: true },
      { label: 'Recebido', render: (p) => money(p.received_cents), num: true }, { label: 'Troco', render: (p) => (p.change_cents ? money(p.change_cents) : ''), num: true },
      s.fees_cents !== undefined ? { label: 'Taxa est.', render: (p) => (p.fee_cents ? money(p.fee_cents) : ''), num: true } : null].filter(Boolean), s.payments);
    const info = h('dl', { class: 'kv' }, h('dt', {}, 'Data'), h('dd', {}, fmtDateTime(s.created_at)), h('dt', {}, 'Vendedor'), h('dd', {}, s.seller), h('dt', {}, 'Cliente'), h('dd', {}, s.customer_name || '—'),
      h('dt', {}, 'Total'), h('dd', {}, h('b', {}, money(s.total_cents))), s.profit_cents !== undefined ? [h('dt', {}, 'Lucro estimado'), h('dd', {}, money(s.profit_cents - (s.fees_cents || 0)) + ' (custo real e taxas descontados)')] : null,
      s.status === 'cancelada' ? [h('dt', {}, 'Cancelada'), h('dd', {}, `${fmtDateTime(s.cancelled_at)} por ${s.cancelled_by_name}: ${s.cancel_reason}`)] : null,
      s.refunded_cents ? [h('dt', {}, 'Devolvido'), h('dd', {}, money(s.refunded_cents))] : null);
    const buttons = [{ label: 'Reimprimir comprovante', onClick: () => openPrint(`/print/sale/${id}?w=80&print=1`) }, { label: 'Comprovante A4', onClick: () => openPrint(`/print/sale/${id}?w=a4&print=1`) }];
    if (s.status === 'concluida') {
      buttons.push({ label: 'Devolução / troca', onClick: async (close) => { close(); (await import('./aftersales.js')).returnDialog(s); } });
      buttons.push({ label: 'Cancelar venda', kind: 'danger', onClick: async (close) => {
        const reason = await askText('Cancelar venda #' + id, 'Motivo do cancelamento (obrigatório)', { multiline: true, okLabel: 'Cancelar venda' });
        if (!reason) return;
        const r = await withAuth((auth) => api.post(`/api/sales/${id}/cancel`, { reason, authorization: auth }), 'Cancelar venda exige autorização de supervisor.');
        if (r) { toast('Venda cancelada e estoque devolvido.', 'good'); close(true); load(); }
      } });
    }
    await modal({ title: `Venda #${id}`, size: 'wide', content: [info, h('h3', {}, 'Itens'), items, h('h3', {}, 'Pagamentos'), pays], cancelLabel: 'Fechar', buttons });
  }
  el.append(h('div', { class: 'toolbar' }, field('De', from), field('Até', to), field('Buscar', q, 'grow'), field('Situação', status), h('button', { class: 'btn primary', onclick: () => load().catch(errorToast) }, 'Filtrar')), out);
  q.addEventListener('keydown', (e) => { if (e.key === 'Enter') load().catch(errorToast); });
  await load();
}
