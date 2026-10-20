import { api, qs } from '../api.js';
import { h, clear, money, field, modal, toast, errorToast, table, badge, fmtDate, fmtDateTime, debounce, confirmBox } from '../ui.js';
import { can } from '../state.js';
import { customerDialog } from './shared.js';

export default async function ({ el, route }) {
  const isCust = route === 'clientes';
  const base = isCust ? '/api/customers' : '/api/suppliers';
  const q = h('input', { placeholder: 'Nome, telefone ou CPF/CNPJ', autofocus: true }), inactive = h('input', { type: 'checkbox' });
  const out = h('div');
  const canEdit = isCust ? can('ver_clientes') : can('gerenciar_produtos');
  async function edit(row = null) {
    if (isCust) return customerDialog(row);
    const i = { name: h('input', { value: row?.name || '' }), phone: h('input', { value: row?.phone || '' }), email: h('input', { value: row?.email || '' }), doc: h('input', { value: row?.doc || '' }), notes: h('textarea', {}, row?.notes || '') };
    return modal({ title: row ? 'Editar fornecedor' : 'Novo fornecedor', content: h('div', { class: 'fields' }, field('Nome ou razão social *', i.name, 'wide'), field('Telefone', i.phone), field('E-mail', i.email), field('CPF/CNPJ', i.doc, 'wide'), field('Observações', i.notes, 'wide')),
      buttons: [{ label: 'Salvar', kind: 'primary', onClick: async (close) => { const b = { name: i.name.value, phone: i.phone.value, email: i.email.value, doc: i.doc.value, notes: i.notes.value };
        if (row) await api.put(`${base}/${row.id}`, b); else await api.post(base, b); toast('Cadastro salvo.', 'good'); close(true); } }] });
  }
  async function load() {
    const rows = await api.get(base + qs({ q: q.value.trim(), inactive: inactive.checked ? 1 : '' })); clear(out);
    out.append(h('p', { class: 'muted' }, `${rows.length} cadastro(s)`), table([{ label: 'Nome', render: (r) => h('b', {}, r.name) }, { label: 'Telefone', render: (r) => r.phone || '' }, { label: 'E-mail', render: (r) => r.email || '' }, { label: 'CPF/CNPJ', render: (r) => r.doc || '' },
      { label: '', render: (r) => (r.active ? '' : badge('Inativo', 'bad')) }], rows, { onRow: history, empty: 'Nenhum cadastro encontrado.' }));
  }
  async function history(row) {
    const hist = await api.get(`${base}/${row.id}/history`); const c = hist.customer || hist.supplier; const content = [];
    content.push(h('dl', { class: 'kv' }, h('dt', {}, 'Telefone'), h('dd', {}, c.phone || '—'), h('dt', {}, 'E-mail'), h('dd', {}, c.email || '—'), h('dt', {}, 'CPF/CNPJ'), h('dd', {}, c.doc || '—'), h('dt', {}, 'Cadastro'), h('dd', {}, fmtDate(c.created_at)), h('dt', {}, 'Observações'), h('dd', {}, c.notes || '—')));
    if (isCust) {
      content.push(h('div', { class: 'cards' }, h('div', { class: 'card stat' }, h('div', { class: 'l' }, 'Total comprado'), h('div', { class: 'v' }, money(hist.total_bought_cents))), h('div', { class: 'card stat' + (hist.pending_cents ? ' alert' : '') }, h('div', { class: 'l' }, 'Pendências a receber'), h('div', { class: 'v' }, money(hist.pending_cents)))),
        h('h3', {}, 'Histórico de compras'), table([{ label: 'Venda', render: (s) => '#' + s.id }, { label: 'Data', render: (s) => fmtDateTime(s.created_at) }, { label: 'Total', render: (s) => money(s.total_cents), num: true }, { label: 'Situação', key: 'status' }], hist.sales, { empty: 'Nenhuma compra.' }),
        h('h3', {}, 'Histórico de serviços'), table([{ label: 'OS', render: (o) => '#' + o.id }, { label: 'Entrada', render: (o) => fmtDate(o.entry_at) }, { label: 'Aparelho', render: (o) => `${o.brand} ${o.model}` }, { label: 'Total', render: (o) => money(o.total_cents), num: true }, { label: 'Pago', render: (o) => money(o.paid_cents), num: true }, { label: 'Situação', key: 'status' }], hist.orders, { empty: 'Nenhum serviço.' }),
        hist.receivables.length ? [h('h3', {}, 'Pendências lançadas'), table([{ label: 'Vencimento', render: (r) => fmtDate(r.due_date) }, { label: 'Descrição', key: 'description' }, { label: 'Valor', render: (r) => money(r.amount_cents), num: true }], hist.receivables)] : null);
    } else {
      content.push(h('h3', {}, 'Produtos fornecidos'), table([{ label: 'Produto', key: 'name' }, { label: 'SKU', key: 'sku' }, hist.products[0]?.cost_cents !== undefined ? { label: 'Custo', render: (p) => money(p.cost_cents), num: true } : null, { label: 'Estoque', key: 'qty', num: true }].filter(Boolean), hist.products, { empty: 'Nenhum produto vinculado.' }),
        h('h3', {}, 'Entradas de mercadoria'), table([{ label: 'Data', render: (e) => fmtDateTime(e.created_at) }, { label: 'Produto', key: 'name' }, { label: 'Qtd.', key: 'qty', num: true }, hist.entries[0]?.unit_cost_cents !== undefined ? { label: 'Custo unit.', render: (e) => (e.unit_cost_cents != null ? money(e.unit_cost_cents) : ''), num: true } : null].filter(Boolean), hist.entries, { empty: 'Nenhuma entrada.' }),
        h('h3', {}, 'Aparelhos comprados'), table([{ label: 'Código', key: 'code' }, { label: 'Aparelho', render: (d) => `${d.brand} ${d.model}` }, { label: 'Entrada', render: (d) => fmtDate(d.entry_date) }, { label: 'Situação', key: 'status' }], hist.devices, { empty: 'Nenhum.' }),
        h('h3', {}, 'Contas a pagar'), table([{ label: 'Vencimento', render: (p) => fmtDate(p.due_date) }, { label: 'Descrição', key: 'description' }, { label: 'Valor', render: (p) => money(p.amount_cents), num: true }, { label: 'Situação', render: (p) => (p.paid_at ? badge('Pago', 'good') : badge('Em aberto', 'warn')) }], hist.payables, { empty: 'Nenhuma conta.' }));
    }
    const buttons = canEdit ? [{ label: 'Editar', onClick: async (close) => { close(); const r = await edit(c); if (r) load(); } }, { label: row.active ? 'Inativar' : 'Reativar', onClick: async (close) => { if (await confirmBox(row.active ? 'Inativar este cadastro? O histórico é mantido.' : 'Reativar cadastro?')) { await api.post(`${base}/${row.id}/active`, { active: !row.active }); close(); load(); } } }] : [];
    modal({ title: c.name, size: 'wide', content, buttons, cancelLabel: 'Fechar' });
  }
  el.append(h('div', { class: 'toolbar' }, field('Buscar', q, 'grow'), h('label', { class: 'check' }, inactive, 'Mostrar inativos'), canEdit ? h('button', { class: 'btn primary', onclick: async () => { const r = await edit(); if (r) load(); } }, isCust ? '+ Novo cliente' : '+ Novo fornecedor') : null), out);
  q.addEventListener('input', debounce(() => load().catch(errorToast), 250)); inactive.addEventListener('change', () => load().catch(errorToast));
  await load();
}
