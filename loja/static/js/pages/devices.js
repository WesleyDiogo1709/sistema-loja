import { api, qs } from '../api.js';
import { h, clear, money, moneyInput, dateInput, field, select, modal, askText, toast, errorToast, table, badge, fmtDate, fmtDateTime, debounce, todayISO, STATUS_DEVICE } from '../ui.js';
import { can } from '../state.js';

export default async function ({ el }) {
  const q = h('input', { placeholder: 'Buscar por IMEI, nº de série, código (APL...) ou modelo', autofocus: true });
  const st = select([['', 'Todas as situações'], ...Object.entries(STATUS_DEVICE).map(([k, v]) => [k, v[0]])], '');
  const out = h('div');
  const stBadge = (s) => badge(STATUS_DEVICE[s][0], STATUS_DEVICE[s][1]);
  async function load() {
    const rows = await api.get('/api/devices' + qs({ q: q.value.trim(), status: st.value }));
    clear(out); const showCost = rows.length && rows[0].cost_cents !== undefined;
    out.append(h('p', { class: 'muted' }, `${rows.length} aparelho(s)`), table([{ label: 'Código', key: 'code' }, { label: 'Aparelho', render: (d) => h('div', {}, h('b', {}, `${d.brand} ${d.model}`), h('div', { class: 'muted' }, [d.storage, d.color].filter(Boolean).join(' · '))) },
      { label: 'IMEI 1', render: (d) => d.imei1 || '—' }, { label: 'Série', render: (d) => d.serial || '—' }, { label: 'Bateria', render: (d) => (d.battery_health != null ? d.battery_health + '%' : '—') },
      showCost ? { label: 'Custo', render: (d) => money(d.cost_cents), num: true } : null, { label: 'Preço', render: (d) => money(d.price_cents), num: true }, { label: 'Situação', render: (d) => stBadge(d.status) }].filter(Boolean), rows,
      { onRow: detail, empty: 'Nenhum aparelho encontrado.' }));
  }
  async function form(d = null) {
    const i = { brand: h('input', { value: d?.brand || 'Apple' }), model: h('input', { value: d?.model || '', placeholder: 'iPhone 13' }), storage: h('input', { value: d?.storage || '', placeholder: '128 GB' }), color: h('input', { value: d?.color || '' }),
      imei1: h('input', { value: d?.imei1 || '', inputmode: 'numeric', maxlength: 17, placeholder: '15 dígitos' }), imei2: h('input', { value: d?.imei2 || '', inputmode: 'numeric', maxlength: 17 }), serial: h('input', { value: d?.serial || '' }),
      battery: h('input', { type: 'number', min: 0, max: 100, value: d?.battery_health ?? '' }), condition: select(['', 'Excelente', 'Muito bom', 'Bom', 'Regular', 'Com marcas de uso'], d?.condition || ''),
      origin: h('input', { value: d?.origin || '', placeholder: 'Ex.: compra de cliente, troca, fornecedor' }), supplier: h('input', { value: d?.supplier || '' }),
      cost: moneyInput(d?.cost_cents || 0), price: moneyInput(d?.price_cents || 0), entry: dateInput(d?.entry_date || todayISO()), warranty: h('input', { type: 'number', min: 90, value: d?.warranty_days || 90 }), notes: h('textarea', {}, d?.notes || '') };
    const cost = can('ver_custos');
    return modal({ title: d ? `Editar aparelho ${d.code}` : 'Cadastrar aparelho', size: 'wide', content: h('div', { class: 'fields' }, field('Marca *', i.brand), field('Modelo *', i.model), field('Capacidade', i.storage), field('Cor', i.color), field('IMEI 1', i.imei1), field('IMEI 2 (se houver)', i.imei2), field('Número de série', i.serial),
      field('Saúde da bateria (%)', i.battery), field('Estado de conservação', i.condition), field('Origem do aparelho', i.origin), field('Fornecedor', i.supplier), cost ? field('Custo de compra (R$)', i.cost) : null, field('Preço de venda (R$)', i.price), field('Data de entrada', i.entry),
      field('Garantia (dias, mínimo 90)', i.warranty), field('Observações', i.notes, 'wide')),
      buttons: [{ label: 'Salvar aparelho', kind: 'primary', onClick: async (close) => {
        const body = { brand: i.brand.value, model: i.model.value, storage: i.storage.value, color: i.color.value, imei1: i.imei1.value, imei2: i.imei2.value, serial: i.serial.value, battery_health: i.battery.value, condition: i.condition.value,
          origin: i.origin.value, supplier: i.supplier.value, price_cents: i.price.cents(), entry_date: i.entry.iso() || todayISO(), warranty_days: +i.warranty.value || 90, notes: i.notes.value };
        if (cost) body.cost_cents = i.cost.cents();
        const r = d ? await api.put('/api/devices/' + d.id, body) : await api.post('/api/devices', body); toast(`Aparelho salvo (${r.code}).`, 'good'); close(r); load(); } }] });
  }
  async function detail(row) {
    const d = await api.get('/api/devices/' + row.id);
    const info = h('dl', { class: 'kv' }, h('dt', {}, 'Código'), h('dd', {}, d.code), h('dt', {}, 'Situação'), h('dd', {}, stBadge(d.status), d.reserved_for ? ' para ' + d.reserved_for : ''), h('dt', {}, 'IMEI 1 / 2'), h('dd', {}, `${d.imei1 || '—'} / ${d.imei2 || '—'}`),
      h('dt', {}, 'Série'), h('dd', {}, d.serial || '—'), h('dt', {}, 'Bateria'), h('dd', {}, d.battery_health != null ? d.battery_health + '%' : '—'), h('dt', {}, 'Conservação'), h('dd', {}, d.condition || '—'), h('dt', {}, 'Origem'), h('dd', {}, d.origin || '—'),
      h('dt', {}, 'Fornecedor'), h('dd', {}, d.supplier || '—'), d.cost_cents !== undefined ? [h('dt', {}, 'Custo'), h('dd', {}, money(d.cost_cents))] : null, h('dt', {}, 'Preço'), h('dd', {}, money(d.price_cents)),
      h('dt', {}, 'Entrada'), h('dd', {}, fmtDate(d.entry_date)), h('dt', {}, 'Garantia'), h('dd', {}, d.warranty_days + ' dias'), d.last_sale ? [h('dt', {}, 'Última venda'), h('dd', {}, `#${d.last_sale.id} em ${fmtDate(d.last_sale.created_at)} (garantia até ${fmtDate(d.last_sale.warranty_ends)})`)] : null);
    const acts = h('div', { class: 'row' });
    if (can('gerenciar_aparelhos') && d.status !== 'vendido') {
      const setSt = (s, label) => h('button', { class: 'btn', onclick: async () => { let who = ''; if (s === 'reservado') { who = await askText('Reservar aparelho', 'Reservado para (nome do cliente)', { min: 2 }); if (!who) return; } await api.post(`/api/devices/${d.id}/status`, { status: s, reserved_for: who }); toast('Situação atualizada.', 'good'); document.querySelector('.overlay:last-child .modal-head button').click(); load(); } }, label);
      acts.append(...Object.entries(STATUS_DEVICE).filter(([k]) => k !== 'vendido' && k !== d.status).map(([k, v]) => setSt(k, 'Marcar como ' + v[0].toLowerCase())));
    }
    if (can('gerenciar_aparelhos')) acts.append(h('button', { class: 'btn', onclick: async () => { document.querySelector('.overlay:last-child .modal-head button').click(); await form(d); } }, 'Editar dados'));
    const ev = table([{ label: 'Data', render: (e) => fmtDateTime(e.created_at) }, { label: 'Evento', key: 'event' }, { label: 'Situação', render: (e) => e.status || '' }, { label: 'Observação', render: (e) => e.note || '' }, { label: 'Usuário', render: (e) => e.user_name || '' }], d.events);
    const rep = d.repairs.length ? [h('h3', {}, 'Reparos na assistência'), table([{ label: 'OS', render: (r) => '#' + r.id }, { label: 'Entrada', render: (r) => fmtDate(r.entry_at) }, { label: 'Defeito', key: 'defect' }, { label: 'Situação', key: 'status' }], d.repairs)] : [];
    modal({ title: `${d.brand} ${d.model} ${d.storage || ''} ${d.color || ''}`, size: 'wide', content: [info, acts, h('h3', {}, 'Histórico do aparelho'), ev, ...rep], cancelLabel: 'Fechar' });
  }
  el.append(h('div', { class: 'toolbar' }, field('Buscar', q, 'grow'), field('Situação', st), can('gerenciar_aparelhos') ? h('button', { class: 'btn primary', onclick: () => form() }, '+ Cadastrar aparelho') : null), out);
  q.addEventListener('input', debounce(() => load().catch(errorToast), 200)); st.addEventListener('change', () => load().catch(errorToast));
  q.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); load().catch(errorToast); } });
  await load();
}
