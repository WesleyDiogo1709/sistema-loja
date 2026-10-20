import { api, qs } from '../api.js';
import { h, clear, money, moneyInput, field, select, modal, toast, errorToast, table, badge, fmtDate, fmtDateTime, withAuth, tabs } from '../ui.js';
import { state, can, methodLabel } from '../state.js';

export async function returnDialog(sale) {
  const rows = sale.items.filter((i) => i.qty - (i.returned_qty || 0) > 0).map((i) => {
    const max = i.qty - (i.returned_qty || 0);
    return { it: i, max, qty: h('input', { type: 'number', min: 0, max, value: 0, style: { width: '70px' } }), restock: h('input', { type: 'checkbox', checked: true }) };
  });
  if (!rows.length) { toast('Todos os itens desta venda já foram devolvidos.', 'bad'); return; }
  const kind = select([['devolucao', 'Devolução (cliente recebe de volta)'], ['troca', 'Troca (a diferença é cobrada em uma nova venda)']], 'devolucao');
  const reason = h('textarea', { placeholder: 'Motivo (obrigatório)' }), method = select(state.methods.filter((m) => m.type !== 'card' || true).map((m) => [m.key, m.label]), 'dinheiro'), refund = moneyInput(0);
  const hint = h('div', { class: 'muted' });
  const recalc = () => { const total = rows.reduce((a, r) => a + Math.round(r.it.total_cents * (+r.qty.value || 0) / r.it.qty), 0); hint.textContent = `Valor dos itens selecionados: ${money(total)}`; if (kind.value === 'devolucao') refund.setCents(total); else refund.setCents(0); };
  rows.forEach((r) => r.qty.addEventListener('input', recalc)); kind.addEventListener('change', recalc);
  await modal({ title: `Devolução / troca — venda #${sale.id}`, size: 'wide', content: [table([{ label: 'Item', render: (r) => r.it.product_name }, { label: 'Vendido', render: (r) => r.it.qty, num: true }, { label: 'Devolver', render: (r) => r.qty }, { label: 'Volta ao estoque?', render: (r) => h('label', { class: 'check' }, r.restock, 'Sim, está em condição de revenda') }], rows),
    field('Tipo', kind), field('Motivo', reason), field('Devolver dinheiro por', method), field('Valor a devolver ao cliente (R$)', refund), hint,
    h('div', { class: 'muted' }, 'Sem condição de revenda: o item entra e sai do estoque como avaria, o custo vira perda e o valor aparece no relatório de perdas.')],
    buttons: [{ label: 'Registrar', kind: 'primary', onClick: async (close) => {
      const items = rows.filter((r) => +r.qty.value > 0).map((r) => ({ sale_item_id: r.it.id, qty: +r.qty.value, restock: r.restock.checked }));
      if (!items.length) { toast('Informe a quantidade de ao menos um item.', 'bad'); return; }
      const res = await withAuth((auth) => api.post('/api/returns', { sale_id: sale.id, kind: kind.value, reason: reason.value, items, refund_method: method.value, refund_cents: refund.cents(), authorization: auth }), 'Devoluções e trocas exigem autorização de supervisor.');
      if (res) { toast('Devolução registrada.', 'good'); close(true); } } }] });
}

export default async function ({ el }) {
  const box = h('div'); let tab = 'claims';
  const head = tabs([['claims', 'Reclamações de garantia'], ['lookup', 'Consultar garantia'], ['returns', 'Devoluções e trocas']], (k) => { tab = k; draw(); }, tab);
  el.append(head, box);
  async function draw() {
    clear(box);
    if (tab === 'claims') return claims();
    if (tab === 'lookup') return lookup();
    return returns();
  }
  async function claims(prefill) {
    const st = select([['', 'Todas'], ['aberta', 'Abertas'], ['em_analise', 'Em análise'], ['resolvida', 'Resolvidas'], ['negada', 'Negadas']], ''), q = h('input', { placeholder: 'Cliente, item ou nº da venda' });
    const out = h('div');
    const load = async () => { const rows = await api.get('/api/warranty/claims' + qs({ status: st.value, q: q.value.trim() })); clear(out);
      out.append(table([{ label: 'Nº', key: 'id' }, { label: 'Abertura', render: (c) => fmtDate(c.opened_at) }, { label: 'Item', key: 'item_desc' }, { label: 'Cliente', render: (c) => c.customer_name || '—' }, { label: 'Defeito', render: (c) => c.defect.slice(0, 50) },
        { label: 'Na garantia?', render: (c) => badge(c.in_warranty ? 'Sim' : 'Fora do prazo', c.in_warranty ? 'good' : 'warn') }, { label: 'Custo', render: (c) => (c.cost_cents ? money(c.cost_cents) : ''), num: true },
        { label: 'Situação', render: (c) => badge(c.status.replace('_', ' '), c.status === 'resolvida' ? 'good' : c.status === 'negada' ? 'bad' : 'warn') }], rows, { onRow: openClaim, empty: 'Nenhuma reclamação registrada.' })); };
    box.append(h('div', { class: 'toolbar' }, field('Situação', st), field('Buscar', q, 'grow'), h('button', { class: 'btn primary', onclick: () => newClaim() }, '+ Nova reclamação')), out);
    st.addEventListener('change', load); q.addEventListener('input', () => load()); await load();
    if (prefill) newClaim(prefill);
  }
  async function newClaim(prefill = {}) {
    const i = { item: h('input', { value: prefill.description || '' }), name: h('input', { value: prefill.customer_name || '' }), phone: h('input', { value: prefill.customer_phone || '' }), defect: h('textarea', { placeholder: 'Defeito relatado pelo cliente' }) };
    await modal({ title: 'Nova reclamação de garantia', content: [prefill.ref ? h('div', { class: 'alertbox good' }, `Vinculada a: ${prefill.ref}`) : h('div', { class: 'muted' }, 'Para vincular a uma venda ou OS, use "Consultar garantia".'), field('Item / serviço', i.item), field('Cliente', i.name), field('Telefone', i.phone), field('Defeito relatado *', i.defect)],
      buttons: [{ label: 'Registrar', kind: 'primary', onClick: async (close) => { await api.post('/api/warranty/claims', { sale_item_id: prefill.sale_item_id, order_id: prefill.order_id, item_desc: i.item.value, customer_name: i.name.value, customer_phone: i.phone.value, defect: i.defect.value }); toast('Reclamação registrada.', 'good'); close(true); draw(); } }] });
  }
  async function openClaim(c) {
    const diag = h('textarea', {}, c.diagnosis || ''), sol = h('textarea', {}, c.solution || ''), cost = moneyInput(c.cost_cents), res = select([['', '—'], ['reparo', 'Reparo'], ['troca', 'Troca do produto'], ['reembolso', 'Reembolso']], c.resolution || ''), closed = ['resolvida', 'negada'].includes(c.status);
    const upd = async (status, close) => { await api.put('/api/warranty/claims/' + c.id, { status, diagnosis: diag.value, solution: sol.value, cost_cents: cost.cents() || 0, resolution: res.value }); toast('Reclamação atualizada.', 'good'); close(true); draw(); };
    modal({ title: `Reclamação #${c.id}`, size: 'wide', cancelLabel: 'Fechar', content: [h('dl', { class: 'kv' }, h('dt', {}, 'Item'), h('dd', {}, c.item_desc), h('dt', {}, 'Cliente'), h('dd', {}, `${c.customer_name || '—'} ${c.customer_phone || ''}`), h('dt', {}, 'Venda / OS'), h('dd', {}, c.sale_id ? 'Venda #' + c.sale_id : c.order_id ? 'OS #' + c.order_id : '—'),
      h('dt', {}, 'Defeito'), h('dd', {}, c.defect), h('dt', {}, 'Responsável'), h('dd', {}, c.responsible_name || '—'), h('dt', {}, 'Dentro do prazo'), h('dd', {}, c.in_warranty ? 'Sim' : 'Não — fora da garantia contratual; confira a garantia legal antes de negar.')),
      field('Diagnóstico', diag), field('Solução / justificativa', sol), field('Resolução', res), can('ver_custos') || true ? field('Custo para a loja (R$)', cost) : null],
      buttons: closed ? [] : [{ label: 'Em análise', onClick: (close) => upd('em_analise', close) }, { label: 'Negar garantia', kind: 'danger', onClick: (close) => upd('negada', close) }, { label: 'Resolver', kind: 'primary', onClick: (close) => upd('resolvida', close) }] });
  }
  async function lookup() {
    const q = h('input', { placeholder: 'Nº da venda, IMEI, série, nº da OS, telefone ou nome do cliente', style: { fontSize: '16px' } }), out = h('div');
    const run = async () => { clear(out); if (q.value.trim().length < 2) return; const rows = await api.get('/api/warranty/lookup' + qs({ q: q.value.trim() }));
      out.append(table([{ label: 'Origem', key: 'ref' }, { label: 'Item', key: 'description' }, { label: 'Cliente', render: (r) => r.customer_name || '—' }, { label: 'Início', render: (r) => fmtDate(r.start) }, { label: 'Termina', render: (r) => fmtDate(r.ends) },
        { label: 'Garantia', render: (r) => badge(r.in_warranty ? 'Vigente' : 'Vencida', r.in_warranty ? 'good' : 'bad') }, can('gerenciar_garantias') ? { label: '', render: (r) => h('button', { class: 'btn small', onclick: () => { tab = 'claims'; [...head.children].forEach((b, k) => b.classList.toggle('active', k === 0)); clear(box); claims(r); } }, 'Abrir reclamação') } : null].filter(Boolean), rows, { empty: 'Nada encontrado com esse dado.' })); };
    q.addEventListener('keydown', (e) => { if (e.key === 'Enter') run().catch(errorToast); });
    box.append(h('div', { class: 'toolbar' }, field('Buscar', q, 'grow'), h('button', { class: 'btn primary', onclick: () => run().catch(errorToast) }, 'Consultar')), out, h('p', { class: 'muted' }, 'A garantia legal de 90 dias para bens duráveis (CDC, art. 26) não pode ser reduzida. Prazos maiores podem ser definidos por produto, aparelho ou serviço.')); q.focus();
  }
  async function returns() {
    const rows = await api.get('/api/returns');
    box.append(table([{ label: 'Data', render: (r) => fmtDateTime(r.created_at) }, { label: 'Venda', render: (r) => '#' + r.sale_id }, { label: 'Tipo', render: (r) => (r.kind === 'troca' ? 'Troca' : 'Devolução') }, { label: 'Itens', render: (r) => r.items.map((i) => `${i.qty}x ${i.product_name}${i.restock ? '' : ' (avaria)'}`).join(', ') },
      { label: 'Motivo', key: 'reason' }, { label: 'Devolvido', render: (r) => money(r.refund_cents), num: true }, { label: 'Responsável', key: 'user_name' }], rows, { empty: 'Nenhuma devolução ou troca registrada.' }),
      h('p', { class: 'muted' }, 'Para registrar uma devolução, abra a venda em "Histórico de vendas" e use o botão "Devolução / troca".'));
  }
  await draw();
}
