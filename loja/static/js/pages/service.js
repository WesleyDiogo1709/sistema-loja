import { api, qs } from '../api.js';
import { h, clear, money, moneyInput, dateInput, field, select, modal, toast, errorToast, table, badge, fmtDate, fmtDateTime, debounce, todayISO, withAuth, openPrint, askText, confirmBox } from '../ui.js';
import { state, can, methodLabel } from '../state.js';
import { customerPicker } from './shared.js';

const STATUS = { recebido: 'Recebido', em_diagnostico: 'Em diagnóstico', aguardando_aprovacao: 'Aguardando aprovação', aguardando_peca: 'Aguardando peça', em_reparo: 'Em reparo', em_testes: 'Em testes', pronto_retirada: 'Pronto para retirada', entregue: 'Entregue', cancelado: 'Cancelado' };
const KIND = { recebido: '', em_diagnostico: 'info', aguardando_aprovacao: 'warn', aguardando_peca: 'warn', em_reparo: 'info', em_testes: 'info', pronto_retirada: 'good', entregue: '', cancelado: 'bad' };

export default async function ({ el }) {
  const techs = await api.get('/api/users/basic').catch(() => []);
  const q = h('input', { placeholder: 'Nº da OS, cliente, telefone, IMEI ou modelo', autofocus: true });
  const st = select([['', 'Todas'], ...Object.entries(STATUS)], ''), open = h('input', { type: 'checkbox', checked: true }), unclaimed = h('input', { type: 'checkbox' });
  const out = h('div');
  async function load() {
    const rows = await api.get('/api/os' + qs({ q: q.value.trim(), status: st.value, open: open.checked && !st.value ? 1 : '', unclaimed: unclaimed.checked ? 1 : '' }));
    clear(out);
    out.append(h('p', { class: 'muted' }, `${rows.length} ordem(ns)`), table([{ label: 'OS', render: (o) => h('b', {}, '#' + o.id) }, { label: 'Entrada', render: (o) => fmtDate(o.entry_at) }, { label: 'Cliente', render: (o) => h('div', {}, o.customer_name, h('div', { class: 'muted' }, o.customer_phone || '')) },
      { label: 'Aparelho', render: (o) => `${o.brand} ${o.model}` }, { label: 'Defeito', render: (o) => o.defect.slice(0, 50) }, { label: 'Técnico', render: (o) => o.technician_name || '—' },
      { label: 'Prazo', render: (o) => (o.deadline ? h('span', {}, fmtDate(o.deadline), ' ', o.overdue ? badge('Atrasada', 'bad') : null) : '—') }, { label: 'Total', render: (o) => money(o.total_cents), num: true },
      { label: 'Saldo', render: (o) => (o.balance_cents > 0 ? money(o.balance_cents) : ''), num: true }, { label: 'Situação', render: (o) => badge(o.status_label, KIND[o.status]) }], rows, { onRow: (o) => detail(o.id), empty: 'Nenhuma ordem de serviço encontrada.' }));
  }
  async function newOrder() {
    let cust = null;
    const i = { name: h('input'), phone: h('input', { placeholder: '(00) 00000-0000' }), brand: h('input', { placeholder: 'Apple, Samsung...' }), model: h('input'), imei: h('input', { placeholder: 'IMEI ou nº de série (se necessário)' }),
      defect: h('textarea', { placeholder: 'O que o cliente relatou' }), state: h('textarea', { placeholder: 'Riscos, trincas, amassados, aparelho liga?' }), acc: h('input', { placeholder: 'Capa, carregador, chip...' }), labor: moneyInput(0),
      deadline: dateInput(todayISO(3)), tech: select([['', 'A definir'], ...techs.map((t) => [t.id, t.name])], ''), warranty: h('input', { type: 'number', min: 90, value: state.settings.default_warranty_days || 90 }), approved: h('input', { type: 'checkbox' }), appNote: h('input', { placeholder: 'Como o cliente autorizou?' }) };
    const pick = h('button', { class: 'btn', type: 'button', onclick: async () => { const c = await customerPicker(); if (c) { cust = c; i.name.value = c.name; i.phone.value = c.phone || ''; } } }, 'Escolher cliente cadastrado');
    await modal({ title: 'Nova ordem de serviço', size: 'wide', content: [pick, h('div', { class: 'fields' }, field('Nome do cliente *', i.name), field('Telefone *', i.phone), field('Marca *', i.brand), field('Modelo *', i.model), field('IMEI / nº de série', i.imei), field('Acessórios recebidos', i.acc),
      field('Defeito relatado *', i.defect, 'wide'), field('Estado físico na entrada', i.state, 'wide'), field('Mão de obra estimada (R$)', i.labor), field('Prazo estimado', i.deadline), field('Técnico responsável', i.tech), field('Garantia do serviço (dias)', i.warranty),
      h('label', { class: 'check wide' }, i.approved, 'O cliente já autorizou o orçamento'), field('Registro da autorização', i.appNote, 'wide'))],
      buttons: [{ label: 'Abrir OS', kind: 'primary', onClick: async (close) => {
        const body = { customer_id: cust ? cust.id : null, customer_name: i.name.value, customer_phone: i.phone.value, brand: i.brand.value, model: i.model.value, imei: i.imei.value, defect: i.defect.value, physical_state: i.state.value, accessories: i.acc.value,
          labor_cents: i.labor.cents() || 0, deadline: i.deadline.iso() || null, technician_id: i.tech.value ? +i.tech.value : null, warranty_days: +i.warranty.value || 90, client_token: crypto.randomUUID() };
        const r = await api.post('/api/os', body);
        if (i.approved.checked) await api.post(`/api/os/${r.id}/approval`, { approved: true, note: i.appNote.value || 'Autorizado na abertura' });
        toast(`OS #${r.id} aberta.`, 'good'); close(r.id); openPrint(`/print/os/${r.id}?print=1`); load(); } }] });
  }
  async function detail(id) {
    const o = await api.get('/api/os/' + id);
    const final = ['entregue', 'cancelado'].includes(o.status);
    const reopen = () => { document.querySelector('.overlay:last-child .modal-head button')?.click(); detail(id); };
    const info = h('div', { class: 'grid2' }, h('dl', { class: 'kv' }, h('dt', {}, 'Cliente'), h('dd', {}, `${o.customer_name} · ${o.customer_phone || ''}`), h('dt', {}, 'Aparelho'), h('dd', {}, `${o.brand} ${o.model}`), h('dt', {}, 'IMEI / série'), h('dd', {}, `${o.imei || '—'} / ${o.serial || '—'}`),
      h('dt', {}, 'Defeito'), h('dd', {}, o.defect), h('dt', {}, 'Estado físico'), h('dd', {}, o.physical_state || '—'), h('dt', {}, 'Acessórios'), h('dd', {}, o.accessories || '—')),
      h('dl', { class: 'kv' }, h('dt', {}, 'Situação'), h('dd', {}, badge(o.status_label, KIND[o.status])), h('dt', {}, 'Entrada'), h('dd', {}, fmtDateTime(o.entry_at)), h('dt', {}, 'Prazo'), h('dd', {}, fmtDate(o.deadline) || '—'), h('dt', {}, 'Técnico'), h('dd', {}, o.technician_name || '—'),
        h('dt', {}, 'Conclusão'), h('dd', {}, fmtDateTime(o.completed_at) || '—'), h('dt', {}, 'Entrega'), h('dd', {}, fmtDateTime(o.delivered_at) || '—'), h('dt', {}, 'Garantia'), h('dd', {}, o.warranty_days + ' dias' + (o.warranty_ends ? ` (até ${fmtDate(o.warranty_ends)})` : '')),
        h('dt', {}, 'Orçamento'), h('dd', {}, o.approved ? badge('Autorizado em ' + fmtDateTime(o.approved_at), 'good') : badge('Sem autorização', 'warn'), o.approved_note ? h('div', { class: 'muted' }, o.approved_note) : null)));
    const diag = h('textarea', { disabled: final }, o.diagnosis || ''), done = h('textarea', { disabled: final }, o.services_done || ''), labor = moneyInput(o.labor_cents, { disabled: final });
    const parts = table([{ label: 'Peça', key: 'name' }, { label: 'Qtd.', key: 'qty', num: true }, { label: 'Valor', render: (p) => money(p.unit_price_cents * p.qty), num: true },
      o.parts.length && o.parts[0].unit_cost_cents !== undefined ? { label: 'Custo', render: (p) => money(p.unit_cost_cents * p.qty), num: true } : null,
      final ? null : { label: '', render: (p) => h('button', { class: 'btn small', onclick: async () => { await api.del(`/api/os/${id}/parts/${p.id}`); toast('Peça removida e devolvida ao estoque.', 'good'); reopen(); } }, 'Remover') }].filter(Boolean), o.parts, { empty: 'Nenhuma peça usada.' });
    const pays = table([{ label: 'Data', render: (p) => fmtDateTime(p.created_at) }, { label: 'Forma', render: (p) => methodLabel(p.method) + (p.installments > 1 ? ` ${p.installments}x` : '') }, { label: 'Valor', render: (p) => money(p.amount_cents), num: true }, { label: '', render: (p) => (p.voided_at ? badge('Estornado', 'bad') : '') }], o.payments, { empty: 'Nenhum pagamento.' });
    const totals = h('dl', { class: 'kv' }, h('dt', {}, 'Peças'), h('dd', {}, money(o.parts_cents)), h('dt', {}, 'Mão de obra'), h('dd', {}, money(o.labor_cents)), o.discount_cents ? [h('dt', {}, 'Desconto'), h('dd', {}, '−' + money(o.discount_cents))] : null,
      h('dt', {}, h('b', {}, 'Total')), h('dd', {}, h('b', {}, money(o.total_cents))), h('dt', {}, 'Pago'), h('dd', {}, money(o.paid_cents)), h('dt', {}, h('b', {}, 'Saldo')), h('dd', {}, h('b', { style: { color: o.balance_cents > 0 ? 'var(--bad)' : 'var(--good)' } }, money(o.balance_cents))));
    const hist = table([{ label: 'Data', render: (e) => fmtDateTime(e.created_at) }, { label: 'Situação', render: (e) => STATUS[e.status] || '' }, { label: 'Observação', render: (e) => e.note || '' }, { label: 'Usuário', render: (e) => e.user_name || '' }], o.events);
    const buttons = [{ label: 'Imprimir OS', onClick: () => openPrint(`/print/os/${id}?print=1`) }];
    const actions = h('div', { class: 'row' });
    if (!final) {
      buttons.push({ label: 'Salvar diagnóstico e valores', kind: 'primary', onClick: async () => { await api.put('/api/os/' + id, { diagnosis: diag.value, services_done: done.value, labor_cents: labor.cents() || 0 }); toast('OS atualizada.', 'good'); reopen(); load(); } });
      actions.append(h('button', { class: 'btn', onclick: () => addPart(id, reopen) }, '+ Peça do estoque'), h('button', { class: 'btn', onclick: () => payment(o, reopen) }, 'Receber pagamento'),
        h('button', { class: 'btn', onclick: () => discount(o, reopen) }, 'Desconto'),
        h('button', { class: 'btn', onclick: async () => { const note = await askText(o.approved ? 'Registrar nova decisão do cliente' : 'Autorização do orçamento', 'Como o cliente autorizou? (assinatura, WhatsApp, ligação...)'); if (!note) return; await api.post(`/api/os/${id}/approval`, { approved: true, note }); toast('Autorização registrada.', 'good'); reopen(); } }, 'Registrar autorização do cliente'),
        h('button', { class: 'btn', onclick: async () => { const note = await askText('Orçamento recusado', 'Observação (opcional)', { required: false }); if (note === undefined) return; await api.post(`/api/os/${id}/approval`, { approved: false, note }); reopen(); } }, 'Cliente recusou'));
    }
    const statusRow = h('div', { class: 'row' }, h('b', {}, 'Mudar situação:'), ...(final ? [] : Object.entries(STATUS).filter(([k]) => k !== o.status && k !== 'cancelado').map(([k, v]) => h('button', { class: 'btn small', onclick: async () => {
      let note = ''; let allow = false;
      if (k === 'entregue' && o.balance_cents > 0) { if (!(await confirmBox(`Há saldo pendente de ${money(o.balance_cents)}. Entregar o aparelho mesmo assim? O saldo ficará em Contas a receber.`, { okLabel: 'Entregar com pendência' }))) return; allow = true; }
      try { await api.post(`/api/os/${id}/status`, { status: k, allow_pending: allow, note }); toast('Situação atualizada.', 'good'); reopen(); load(); } catch (e) { errorToast(e); } } }, v))),
      final ? null : h('button', { class: 'btn small danger', onclick: async () => { const note = await askText('Cancelar OS #' + id, 'Motivo do cancelamento', { multiline: true }); if (!note) return;
        const r = await withAuth((auth) => api.post(`/api/os/${id}/status`, { status: 'cancelado', note, authorization: auth }), 'Cancelar uma OS exige autorização de supervisor.'); if (r) { toast('OS cancelada. Peças devolvidas ao estoque.', 'good'); reopen(); load(); } } }, 'Cancelar OS'));
    await modal({ title: `Ordem de serviço #${o.id}`, size: 'wide', cancelLabel: 'Fechar', buttons, content: [info, o.history.length ? h('div', { class: 'alertbox' }, 'Este aparelho já passou pela assistência: ', o.history.map((x) => `OS #${x.id} (${fmtDate(x.entry_at)}: ${x.defect})`).join(' · ')) : null,
      statusRow, field('Diagnóstico técnico', diag), field('Serviços realizados', done), field('Mão de obra (R$)', labor), h('h3', {}, 'Peças utilizadas'), parts, actions, h('div', { class: 'grid2' }, h('div', {}, h('h3', {}, 'Valores'), totals), h('div', {}, h('h3', {}, 'Pagamentos'), pays)), h('h3', {}, 'Histórico da OS'), hist] });
  }
  async function addPart(id, reopen) {
    const input = h('input', { placeholder: 'Buscar peça no estoque (nome, SKU ou código)' }), out = h('div', { class: 'results' }), qty = h('input', { type: 'number', min: 1, value: 1 });
    let chosen = null; const sel = h('div', { class: 'muted' }, 'Nenhuma peça selecionada.');
    input.addEventListener('input', debounce(async () => { clear(out); if (input.value.trim().length < 2) return; const rows = await api.get('/api/products' + qs({ q: input.value.trim() }));
      rows.slice(0, 10).forEach((p) => out.append(h('button', { type: 'button', onclick: () => { chosen = p; sel.textContent = `${p.name} — ${money(p.price_cents)} (estoque ${p.qty})`; } }, h('span', {}, p.name), h('span', {}, `estoque ${p.qty} · ${money(p.price_cents)}`)))); }, 200));
    await modal({ title: 'Adicionar peça à OS', content: [field('Peça', input), out, sel, field('Quantidade', qty), h('div', { class: 'muted' }, 'A peça é baixada do estoque agora e devolvida se for removida ou se a OS for cancelada.')],
      buttons: [{ label: 'Adicionar', kind: 'primary', onClick: async (close) => { if (!chosen) { toast('Selecione uma peça.', 'bad'); return; } await api.post(`/api/os/${id}/parts`, { product_id: chosen.id, qty: +qty.value }); toast('Peça adicionada.', 'good'); close(true); reopen(); } }] });
  }
  async function discount(o, reopen) {
    const v = moneyInput(o.discount_cents);
    await modal({ title: 'Desconto na OS', size: 'narrow', content: [field('Valor do desconto (R$)', v)], buttons: [{ label: 'Aplicar', kind: 'primary', onClick: async (close) => {
      const r = await withAuth((auth) => api.put('/api/os/' + o.id, { discount_cents: v.cents() || 0, authorization: auth }), 'Desconto exige autorização de supervisor.'); if (r) { close(true); reopen(); } } }] });
  }
  async function payment(o, reopen) {
    const methods = state.methods; const m = select(methods.map((x) => [x.key, x.label]), methods[0].key), amt = moneyInput(o.balance_cents), recv = moneyInput(0), inst = select(Array.from({ length: +state.settings.max_installments || 12 }, (_, k) => [k + 1, k ? `${k + 1}x` : 'À vista']), 1);
    await modal({ title: 'Receber pagamento da OS #' + o.id, size: 'narrow', content: [h('div', { class: 'muted' }, `Saldo: ${money(o.balance_cents)}`), field('Forma', m), field('Valor (R$)', amt), field('Valor recebido em dinheiro (se houver troco)', recv), field('Parcelas (cartão de crédito)', inst)],
      buttons: [{ label: 'Registrar pagamento', kind: 'primary', onClick: async (close) => { const meth = methods.find((x) => x.key === m.value); const p = { method: m.value, amount_cents: amt.cents() };
        if (meth.type === 'cash') p.received_cents = recv.cents() || p.amount_cents; if (meth.installments) p.installments = +inst.value;
        await api.post(`/api/os/${o.id}/payments`, { payments: [p] }); toast('Pagamento registrado.', 'good'); close(true); reopen(); } }] });
  }
  el.append(h('div', { class: 'toolbar' }, field('Buscar', q, 'grow'), field('Situação', st), h('label', { class: 'check' }, open, 'Só em aberto'), h('label', { class: 'check' }, unclaimed, 'Não retirados'), h('button', { class: 'btn primary', onclick: newOrder }, '+ Nova ordem de serviço')), out);
  [q].forEach((x) => x.addEventListener('input', debounce(() => load().catch(errorToast), 250)));
  [st, open, unclaimed].forEach((x) => x.addEventListener('change', () => load().catch(errorToast)));
  await load();
}
