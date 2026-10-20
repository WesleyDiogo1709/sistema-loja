import { api, qs } from '../api.js';
import { h, clear, money, moneyInput, field, select, modal, toast, errorToast, table, badge, fmtDateTime, debounce, askText, confirmBox } from '../ui.js';
import { can } from '../state.js';
import { productDialog } from './shared.js';

const KIND = { entrada_inicial: 'Estoque inicial', entrada: 'Entrada', saida: 'Saída manual', perda: 'Perda', avaria: 'Avaria', troca: 'Para troca', ajuste: 'Ajuste', venda: 'Venda', cancelamento_venda: 'Cancelamento de venda', devolucao: 'Devolução', os_peca: 'Peça em OS', os_estorno: 'Estorno de OS' };

export default async function ({ el }) {
  const q = h('input', { placeholder: 'Buscar por nome, código de barras ou SKU', autofocus: true });
  const cat = select([['', 'Todas as categorias'], ...(await api.get('/api/categories').catch(() => [])).map((c) => [c, c])], '');
  const low = h('input', { type: 'checkbox' }), inactive = h('input', { type: 'checkbox' });
  const out = h('div');
  async function load() {
    const rows = await api.get('/api/products' + qs({ q: q.value.trim(), category: cat.value, low: low.checked ? 1 : '', inactive: inactive.checked ? 1 : '' }));
    clear(out);
    const showCost = rows.length && rows[0].cost_cents !== undefined;
    const cols = [{ label: 'Produto', render: (p) => h('div', {}, h('b', {}, p.name), h('div', { class: 'muted' }, [p.brand, p.model].filter(Boolean).join(' · '))) },
      { label: 'Código', render: (p) => h('div', {}, p.barcode || '—', h('div', { class: 'muted' }, p.sku)) }, { label: 'Categoria', render: (p) => p.category || '' },
      showCost ? { label: 'Custo', render: (p) => money(p.cost_cents), num: true } : null, { label: 'Preço', render: (p) => money(p.price_cents), num: true },
      { label: 'Estoque', render: (p) => h('span', {}, String(p.qty), ' ', p.qty <= p.min_qty ? badge(p.qty <= 0 ? 'Zerado' : 'Baixo', p.qty <= 0 ? 'bad' : 'warn') : null), num: true },
      { label: 'Local', render: (p) => p.location || '' }].filter(Boolean);
    out.append(h('p', { class: 'muted' }, `${rows.length} produto(s)`), table(cols, rows, { onRow: detail, empty: 'Nenhum produto encontrado. Cadastre o primeiro em "Novo produto".' }));
  }
  async function detail(p) {
    const fresh = await api.get('/api/products/' + p.id);
    const hist = await api.get(`/api/products/${p.id}/history`);
    const acts = h('div', { class: 'row' });
    if (can('movimentar_estoque')) { acts.append(btn('Entrada de mercadoria', () => entry(fresh)), btn('Saída / perda / avaria', () => exitDialog(fresh)), btn('Alterar local', () => transfer(fresh))); }
    if (can('ajustar_estoque')) acts.append(btn('Ajustar estoque', () => adjust(fresh)));
    if (can('gerenciar_produtos')) acts.append(btn('Editar', async () => { const r = await productDialog(fresh); if (r) { load(); } }), btn(fresh.active ? 'Inativar' : 'Reativar', async () => {
      if (await confirmBox(fresh.active ? 'Inativar este produto? Ele sai do PDV, mas o histórico é mantido.' : 'Reativar produto?')) { await api.post(`/api/products/${p.id}/active`, { active: !fresh.active }); toast('Produto atualizado.', 'good'); load(); } }));
    const info = h('dl', { class: 'kv' }, h('dt', {}, 'Estoque'), h('dd', {}, h('b', {}, String(fresh.qty)), ` (mínimo ${fresh.min_qty})`), h('dt', {}, 'Preço'), h('dd', {}, money(fresh.price_cents)),
      fresh.cost_cents !== undefined ? [h('dt', {}, 'Custo médio'), h('dd', {}, money(fresh.cost_cents))] : null, h('dt', {}, 'Código de barras'), h('dd', {}, (fresh.barcode || '—') + (fresh.barcode_type ? ` (${fresh.barcode_type})` : '')),
      h('dt', {}, 'SKU'), h('dd', {}, fresh.sku), h('dt', {}, 'Fornecedor'), h('dd', {}, fresh.supplier || '—'), h('dt', {}, 'Local'), h('dd', {}, fresh.location || '—'), h('dt', {}, 'Garantia'), h('dd', {}, fresh.warranty_days + ' dias'),
      h('dt', {}, 'Cadastro'), h('dd', {}, fmtDateTime(fresh.created_at)), h('dt', {}, 'Observações'), h('dd', {}, fresh.notes || '—'));
    const mv = table([{ label: 'Data', render: (m) => fmtDateTime(m.created_at) }, { label: 'Tipo', render: (m) => KIND[m.kind] || m.kind }, { label: 'Qtd.', render: (m) => (m.qty_delta > 0 ? '+' : '') + m.qty_delta, num: true },
      { label: 'Saldo', render: (m) => `${m.qty_before} → ${m.qty_after}`, num: true }, { label: 'Motivo', render: (m) => m.reason || '' }, { label: 'Usuário', render: (m) => m.user_name + (m.authorized_name ? ` (aut. ${m.authorized_name})` : '') }], hist.movements, { empty: 'Sem movimentações.' });
    modal({ title: fresh.name + (fresh.active ? '' : ' (inativo)'), size: 'wide', content: [info, acts, h('h3', {}, 'Histórico de movimentações'), mv], cancelLabel: 'Fechar' });
  }
  const btn = (label, fn) => h('button', { class: 'btn', type: 'button', onclick: () => { document.querySelector('.overlay:last-child .modal-head button')?.click(); fn(); } }, label);
  async function entry(p) {
    const qty = h('input', { type: 'number', min: 1, value: 1 }), cost = moneyInput(p.cost_cents || 0), sup = h('input', { value: p.supplier || '' }), note = h('input', { placeholder: 'Nº da nota, observações...' });
    await modal({ title: 'Entrada de mercadoria: ' + p.name, size: 'narrow', content: [field('Quantidade recebida', qty), can('ver_custos') ? field('Custo unitário desta compra (R$)', cost) : null, field('Fornecedor', sup), field('Observação', note)],
      buttons: [{ label: 'Registrar entrada', kind: 'primary', onClick: async (close) => { await api.post(`/api/products/${p.id}/entry`, { qty: +qty.value, unit_cost_cents: can('ver_custos') ? cost.cents() : null, supplier: sup.value, note: note.value }); toast('Entrada registrada. Estoque atualizado.', 'good'); close(true); load(); } }] });
  }
  async function exitDialog(p) {
    const qty = h('input', { type: 'number', min: 1, value: 1 }), kind = select([['saida', 'Saída manual'], ['perda', 'Perda'], ['avaria', 'Avaria'], ['troca', 'Produto para troca (fornecedor)']], 'saida'), why = h('textarea', { placeholder: 'Justificativa obrigatória' });
    await modal({ title: 'Saída de estoque: ' + p.name, size: 'narrow', content: [h('div', { class: 'muted' }, `Disponível: ${p.qty}`), field('Tipo', kind), field('Quantidade', qty), field('Justificativa', why)],
      buttons: [{ label: 'Registrar saída', kind: 'danger', onClick: async (close) => { await api.post(`/api/products/${p.id}/exit`, { qty: +qty.value, kind: kind.value, reason: why.value }); toast('Saída registrada.', 'good'); close(true); load(); } }] });
  }
  async function adjust(p) {
    const n = h('input', { type: 'number', min: 0, value: p.qty }), why = h('textarea', { placeholder: 'Ex.: contagem física, erro de lançamento' });
    await modal({ title: 'Ajustar estoque: ' + p.name, size: 'narrow', content: [h('div', { class: 'muted' }, `Estoque atual no sistema: ${p.qty}. O ajuste ficará registrado com o seu nome.`), field('Quantidade correta (contada)', n), field('Motivo do ajuste', why)],
      buttons: [{ label: 'Ajustar', kind: 'primary', onClick: async (close) => { await api.post(`/api/products/${p.id}/adjust`, { new_qty: +n.value, reason: why.value }); toast('Estoque ajustado.', 'good'); close(true); load(); } }] });
  }
  async function transfer(p) {
    const loc = h('input', { value: p.location || '' }), note = h('input');
    await modal({ title: 'Mudar local de armazenamento', size: 'narrow', content: [h('div', { class: 'muted' }, `Local atual: ${p.location || 'não informado'}`), field('Novo local', loc), field('Observação', note)],
      buttons: [{ label: 'Transferir', kind: 'primary', onClick: async (close) => { await api.post(`/api/products/${p.id}/transfer`, { location: loc.value, note: note.value }); toast('Local atualizado.', 'good'); close(true); load(); } }] });
  }
  el.append(h('div', { class: 'toolbar' }, field('Buscar', q, 'grow'), field('Categoria', cat), h('label', { class: 'check' }, low, 'Só estoque baixo'), h('label', { class: 'check' }, inactive, 'Mostrar inativos'),
    can('gerenciar_produtos') ? h('button', { class: 'btn primary', onclick: async () => { const p = await productDialog(); if (p) load(); } }, '+ Novo produto') : null), out);
  [q, cat, low, inactive].forEach((x) => x.addEventListener(x === q ? 'input' : 'change', debounce(() => load().catch(errorToast), 200)));
  await load();
}
