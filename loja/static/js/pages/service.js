import { api, qs } from '../api.js';
import { h, clear, money, moneyInput, dateInput, field, select, modal, toast, errorToast, table, badge, fmtDate, fmtDateTime, debounce, todayISO, withAuth, openPrint, askText, confirmBox } from '../ui.js';
import { state, can, methodLabel } from '../state.js';
import { customerPicker } from './shared.js';

const PART_STATUS = { aguardando_compra: 'Aguardando compra', encomendada: 'Encomendada', recebida: 'Recebida', instalada: 'Instalada' };
const PART_KIND = { aguardando_compra: 'warn', encomendada: 'info', recebida: 'info', instalada: 'good', cancelada: 'bad' };
const warrantyTypes = () => { try { return JSON.parse(state.settings.os_warranty_types || '[]'); } catch (e) { return []; } };

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
      deadline: dateInput(todayISO(3)), tech: select([['', 'A definir'], ...techs.map((t) => [t.id, t.name])], ''), wtype: select([['', 'Padrão da loja'], ...warrantyTypes().map((t) => [t.key, `${t.label} (${t.days} dias)`])], ''), warranty: h('input', { type: 'number', min: 90, placeholder: 'dias (opcional)' }), approved: h('input', { type: 'checkbox' }), appNote: h('input', { placeholder: 'Como o cliente autorizou?' }) };
    const pick = h('button', { class: 'btn', type: 'button', onclick: async () => { const c = await customerPicker(); if (c) { cust = c; i.name.value = c.name; i.phone.value = c.phone || ''; } } }, 'Escolher cliente cadastrado');
    await modal({ title: 'Nova ordem de serviço', size: 'wide', content: [pick, h('div', { class: 'fields' }, field('Nome do cliente *', i.name), field('Telefone *', i.phone), field('Marca *', i.brand), field('Modelo *', i.model), field('IMEI / nº de série', i.imei), field('Acessórios recebidos', i.acc),
      field('Defeito relatado *', i.defect, 'wide'), field('Estado físico na entrada', i.state, 'wide'), field('Mão de obra estimada (R$)', i.labor), field('Prazo estimado', i.deadline), field('Técnico responsável', i.tech), field('Tipo de garantia', i.wtype), field('Prazo da garantia (dias, mín. 90)', i.warranty),
      h('label', { class: 'check wide' }, i.approved, 'O cliente já autorizou o orçamento'), field('Registro da autorização', i.appNote, 'wide'))],
      buttons: [{ label: 'Abrir OS', kind: 'primary', onClick: async (close) => {
        const body = { customer_id: cust ? cust.id : null, customer_name: i.name.value, customer_phone: i.phone.value, brand: i.brand.value, model: i.model.value, imei: i.imei.value, defect: i.defect.value, physical_state: i.state.value, accessories: i.acc.value,
          labor_cents: i.labor.cents() || 0, deadline: i.deadline.iso() || null, technician_id: i.tech.value ? +i.tech.value : null, warranty_type: i.wtype.value || null, warranty_days: i.warranty.value ? +i.warranty.value : null, client_token: crypto.randomUUID() };
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
    const wtype = select([['', 'Padrão da loja'], ...warrantyTypes().map((t) => [t.key, `${t.label} (${t.days} dias)`])], o.warranty_type || ''), wdays = h('input', { type: 'number', min: 90, value: o.warranty_days, disabled: final });
    wtype.disabled = final; wtype.addEventListener('change', () => { const t = warrantyTypes().find((x) => x.key === wtype.value); if (t) wdays.value = t.days; });
    const diag = h('textarea', { disabled: final }, o.diagnosis || ''), done = h('textarea', { disabled: final }, o.services_done || ''), labor = moneyInput(o.labor_cents, { disabled: final });
    const costVisible = o.parts_cost_cents !== undefined;       // o servidor só envia custos a quem tem permissão
    const profitVisible = o.profit_partial_cents !== undefined;
    const stockParts = o.parts.filter((p) => p.kind === 'estoque'), looseParts = o.parts.filter((p) => p.kind === 'avulsa');
    const stockTable = table([{ label: 'Peça do estoque', key: 'name' }, { label: 'Qtd.', key: 'qty', num: true }, { label: 'Cobrado', render: (p) => money(p.line_price_cents), num: true },
      costVisible ? { label: 'Custo (estoque)', render: (p) => money(p.line_cost_cents), num: true } : null,
      final ? null : { label: '', render: (p) => h('button', { class: 'btn small', onclick: async () => { await api.del(`/api/os/${id}/parts/${p.id}`); toast('Peça removida e devolvida ao estoque.', 'good'); reopen(); } }, 'Remover') }].filter(Boolean), stockParts, { empty: 'Nenhuma peça do estoque nesta OS.' });
    const looseTable = table([
      { label: 'Peça avulsa (sob encomenda)', render: (p) => h('div', {}, h('b', {}, p.name), p.compat ? h('div', { class: 'muted' }, p.compat) : null, p.notes ? h('div', { class: 'muted' }, p.notes) : null) },
      { label: 'Qtd.', key: 'qty', num: true },
      { label: 'Situação', render: (p) => {
        if (p.cancelled) return badge('Cancelada', 'bad');
        if (final) return badge(PART_STATUS[p.part_status], PART_KIND[p.part_status]);
        const sel = select(Object.entries(PART_STATUS), p.part_status);
        sel.addEventListener('change', async () => { try { await api.post(`/api/os/${id}/parts/${p.id}/status`, { status: sel.value }); toast('Situação da peça atualizada.', 'good'); reopen(); } catch (e) { errorToast(e); sel.value = p.part_status; } });
        return sel; } },
      { label: 'Cobrado', render: (p) => (p.cancelled ? '—' : money(p.line_price_cents)), num: true },
      costVisible ? { label: 'Custo real', render: (p) => (p.unit_cost_cents == null ? badge('Custo pendente', 'warn') : money(p.line_cost_cents) + (p.cancelled ? ' (perdido)' : '')), num: true } : null,
      final ? null : { label: '', render: (p) => h('div', { class: 'row' },
        p.cancelled && !p.cancel_after_purchase ? null : h('button', { class: 'btn small', onclick: () => editLoosePart(o, p, costVisible, reopen) }, p.cancelled ? 'Informar custo' : 'Editar'),
        p.cancelled ? null : (p.part_status === 'aguardando_compra'
          ? h('button', { class: 'btn small', onclick: async () => { if (!(await confirmBox('Remover esta peça da OS? Ela ainda não foi comprada.', { okLabel: 'Remover' }))) return; await api.del(`/api/os/${id}/parts/${p.id}`); toast('Peça removida.', 'good'); reopen(); } }, 'Remover')
          : null),
        p.cancelled ? null : h('button', { class: 'btn small', onclick: () => cancelLoosePart(o, p, reopen) }, 'Cancelar peça')) }].filter(Boolean), looseParts, { empty: 'Nenhuma peça avulsa nesta OS.' });
    const costPanel = costVisible ? h('div', { class: 'card' }, h('h3', {}, 'Custos internos e lucro (não saem na impressão do cliente)'),
      o.cost_incomplete ? h('div', { class: 'alertbox' }, `Falta informar o custo de ${o.parts_cost_missing} peça(s). Enquanto isso o lucro fica incompleto.`) : null,
      h('dl', { class: 'kv' }, h('dt', {}, 'Cobrado pelas peças'), h('dd', {}, money(o.parts_cents)), h('dt', {}, 'Mão de obra'), h('dd', {}, money(o.labor_cents)), h('dt', {}, 'Descontos'), h('dd', {}, '−' + money(o.discount_cents)),
        h('dt', {}, h('b', {}, 'Total cobrado')), h('dd', {}, h('b', {}, money(o.total_cents))),
        h('dt', {}, 'Custo das peças'), h('dd', {}, money(o.parts_cost_cents) + (o.cost_incomplete ? ' (parcial)' : '')),
        h('dt', {}, 'Outros custos'), h('dd', {}, money(o.other_cost_cents) + (o.other_cost_note ? ` — ${o.other_cost_note}` : '')),
        h('dt', {}, h('b', {}, 'Custo total')), h('dd', {}, h('b', {}, money(o.cost_cents))),
        profitVisible ? [h('dt', {}, h('b', {}, 'Lucro bruto estimado')), h('dd', {}, o.profit_cents == null ? h('span', {}, badge('Incompleto', 'warn'), ' ', h('span', { class: 'muted' }, `parcial: ${money(o.profit_partial_cents)}`)) : h('b', {}, money(o.profit_cents)))] : null),
      final ? null : h('div', { class: 'row', style: { marginTop: '10px' } }, h('button', { class: 'btn small', onclick: () => otherCosts(o, reopen) }, 'Lançar outros custos (frete, insumos...)'))) : null;
    const pays = table([{ label: 'Data', render: (p) => fmtDateTime(p.created_at) }, { label: 'Forma', render: (p) => methodLabel(p.method) + (p.installments > 1 ? ` ${p.installments}x` : '') }, { label: 'Valor', render: (p) => money(p.amount_cents), num: true }, { label: '', render: (p) => (p.voided_at ? badge('Estornado', 'bad') : '') }], o.payments, { empty: 'Nenhum pagamento.' });
    const totals = h('dl', { class: 'kv' }, h('dt', {}, 'Peças'), h('dd', {}, money(o.parts_cents)), h('dt', {}, 'Mão de obra'), h('dd', {}, money(o.labor_cents)), o.discount_cents ? [h('dt', {}, 'Desconto'), h('dd', {}, '−' + money(o.discount_cents))] : null,
      h('dt', {}, h('b', {}, 'Total')), h('dd', {}, h('b', {}, money(o.total_cents))), h('dt', {}, 'Pago'), h('dd', {}, money(o.paid_cents)), h('dt', {}, h('b', {}, 'Saldo')), h('dd', {}, h('b', { style: { color: o.balance_cents > 0 ? 'var(--bad)' : 'var(--good)' } }, money(o.balance_cents))));
    const hist = table([{ label: 'Data', render: (e) => fmtDateTime(e.created_at) }, { label: 'Situação', render: (e) => STATUS[e.status] || '' }, { label: 'Observação', render: (e) => e.note || '' }, { label: 'Usuário', render: (e) => e.user_name || '' }], o.events);
    const buttons = [{ label: 'Imprimir via do cliente (térmica 80 mm)', onClick: () => openPrint(`/print/os/${id}?formato=termico&print=1`) }, { label: 'Imprimir A4', onClick: () => openPrint(`/print/os/${id}?formato=a4&print=1`) }];
    const actions = h('div', { class: 'row' });
    if (!final) {
      buttons.push({ label: 'Salvar diagnóstico e valores', kind: 'primary', onClick: async () => { await api.put('/api/os/' + id, { diagnosis: diag.value, services_done: done.value, labor_cents: labor.cents() || 0, warranty_type: wtype.value || null, warranty_days: +wdays.value || 90 }); toast('OS atualizada.', 'good'); reopen(); load(); } });
      actions.append(h('button', { class: 'btn', onclick: () => addPart(id, reopen) }, '+ Peça do estoque'), h('button', { class: 'btn', onclick: () => addLoosePart(o, costVisible, reopen) }, '+ Peça avulsa / sob encomenda'), h('button', { class: 'btn', onclick: () => payment(o, reopen) }, 'Receber pagamento'),
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
      statusRow, field('Diagnóstico técnico', diag), field('Serviços realizados', done), h('div', { class: 'fields' }, field('Mão de obra (R$)', labor), field('Tipo de garantia', wtype), field('Prazo da garantia (dias)', wdays)), h('h3', {}, 'Peças do estoque'), stockTable, h('h3', {}, 'Peças avulsas (compradas sob encomenda)'), looseTable, actions, costPanel, h('div', { class: 'grid2' }, h('div', {}, h('h3', {}, 'Valores'), totals), h('div', {}, h('h3', {}, 'Pagamentos'), pays)), h('h3', {}, 'Histórico da OS'), hist] });
  }
  async function addPart(id, reopen) {
    const input = h('input', { placeholder: 'Buscar peça no estoque (nome, SKU ou código)' }), out = h('div', { class: 'results' }), qty = h('input', { type: 'number', min: 1, value: 1 });
    let chosen = null; const sel = h('div', { class: 'muted' }, 'Nenhuma peça selecionada.');
    input.addEventListener('input', debounce(async () => { clear(out); if (input.value.trim().length < 2) return; const rows = await api.get('/api/products' + qs({ q: input.value.trim() }));
      rows.slice(0, 10).forEach((p) => out.append(h('button', { type: 'button', onclick: () => { chosen = p; sel.textContent = `${p.name} — ${money(p.price_cents)} (estoque ${p.qty})`; } }, h('span', {}, p.name), h('span', {}, `estoque ${p.qty} · ${money(p.price_cents)}`)))); }, 200));
    await modal({ title: 'Adicionar peça à OS', content: [field('Peça', input), out, sel, field('Quantidade', qty), h('div', { class: 'muted' }, 'A peça é baixada do estoque agora e devolvida se for removida ou se a OS for cancelada.')],
      buttons: [{ label: 'Adicionar', kind: 'primary', onClick: async (close) => { if (!chosen) { toast('Selecione uma peça.', 'bad'); return; } await api.post(`/api/os/${id}/parts`, { product_id: chosen.id, qty: +qty.value }); toast('Peça adicionada.', 'good'); close(true); reopen(); } }] });
  }
  function loosePartForm(p, costVisible) {
    const f = { name: h('input', { value: p?.name || '', placeholder: 'Ex.: Tela OLED iPhone 12', maxlength: 120 }), compat: h('input', { value: p?.compat || '', placeholder: 'Modelo ou compatibilidade (opcional)' }),
      qty: h('input', { type: 'number', min: 1, value: p?.qty || 1 }), price: moneyInput(p?.unit_price_cents || 0), cost: moneyInput(p?.unit_cost_cents || 0), supplier: h('input', { value: p?.supplier || '', placeholder: 'Fornecedor (opcional)' }),
      notes: h('textarea', {}, p?.notes || '') };
    if (p && p.unit_cost_cents === 0) f.cost.value = '0,00';
    const fields = [h('div', { class: 'fields' }, field('Nome ou descrição da peça *', f.name, 'wide'), field('Modelo / compatibilidade', f.compat, 'wide'), field('Quantidade *', f.qty), field('Valor cobrado do cliente, por unidade (R$)', f.price),
      costVisible ? field('Custo de aquisição, por unidade (R$) — interno', f.cost) : null, costVisible ? field('Fornecedor — interno', f.supplier) : null, field('Observações', f.notes, 'wide')),
      h('div', { class: 'muted' }, 'A peça vale só para esta OS: não entra no estoque nem cria produto no catálogo. ' + (costVisible ? 'Se ainda não souber o custo, deixe em branco: o lucro da OS aparece como incompleto até você informar.' : 'O custo será lançado pela gerência.'))];
    const body = () => {
      const b = { name: f.name.value, compat: f.compat.value, qty: +f.qty.value, unit_price_cents: f.price.cents() || 0, notes: f.notes.value };
      if (costVisible) { b.unit_cost_cents = f.cost.value.trim() === '' ? null : f.cost.cents(); b.supplier = f.supplier.value; }
      return b;
    };
    return { fields, body };
  }
  async function addLoosePart(o, costVisible, reopen) {
    const form = loosePartForm(null, costVisible);
    await modal({ title: 'Adicionar peça avulsa / sob encomenda', size: 'wide', content: form.fields, buttons: [{ label: 'Adicionar à OS', kind: 'primary', onClick: async (close) => {
      await api.post(`/api/os/${o.id}/loose-parts`, form.body()); toast('Peça avulsa adicionada. Não houve baixa de estoque.', 'good'); close(true); reopen(); } }] });
  }
  async function editLoosePart(o, p, costVisible, reopen) {
    const form = loosePartForm(p, costVisible);
    await modal({ title: p.cancelled ? 'Informar o custo da peça cancelada' : 'Editar peça avulsa', size: 'wide', content: form.fields, buttons: [{ label: 'Salvar', kind: 'primary', onClick: async (close) => {
      await api.put(`/api/os/${o.id}/parts/${p.id}`, form.body()); toast('Peça atualizada.', 'good'); close(true); reopen(); } }] });
  }
  async function cancelLoosePart(o, p, reopen) {
    const bought = ['encomendada', 'recebida', 'instalada'].includes(p.part_status);
    const reason = await askText('Cancelar peça', bought ? 'Motivo (a peça já foi comprada: o custo continua registrado como prejuízo)' : 'Motivo do cancelamento (ex.: cliente desistiu)');
    if (!reason) return;
    const r = await withAuth((auth) => api.post(`/api/os/${o.id}/parts/${p.id}/cancel`, { reason, authorization: auth }), 'Cancelar uma peça já comprada exige autorização de supervisor.');
    if (r) { toast('Peça cancelada.', 'good'); reopen(); }
  }
  async function otherCosts(o, reopen) {
    const v = moneyInput(o.other_cost_cents || 0), note = h('input', { value: o.other_cost_note || '', placeholder: 'Ex.: frete da peça, insumos' });
    await modal({ title: 'Outros custos internos da OS', size: 'narrow', content: [field('Valor (R$)', v), field('Descrição', note), h('div', { class: 'muted' }, 'Entra no custo e no lucro da OS. Não aparece na impressão do cliente.')],
      buttons: [{ label: 'Salvar', kind: 'primary', onClick: async (close) => { await api.put('/api/os/' + o.id, { other_cost_cents: v.cents() || 0, other_cost_note: note.value }); toast('Custos atualizados.', 'good'); close(true); reopen(); } }] });
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
